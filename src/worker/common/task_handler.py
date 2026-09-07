import logging
import time

from operaton.external_task.external_task import ExternalTask, TaskResult
from opentelemetry import trace, metrics
from opentelemetry.propagate import extract, inject
from opentelemetry.trace import set_span_in_context, Status, StatusCode
from opentelemetry.context import attach, detach, Context

from worker.common.config import worker_config
from worker.common.iam import IAMClient
from worker.common.secrets import worker_secrets
from worker.common.log_utils import log_with_context

logger = logging.getLogger(__name__)
tracer = trace.get_tracer(__name__)
meter = metrics.get_meter(__name__)

task_counter = meter.create_counter(
    "demo__tasks_processed_total", unit="1",
    description="Total number of processed operation tasks",
)

task_duration = meter.create_histogram(
    "demo__task_duration_seconds", unit="s",
    description="Duration of task execution (self.execute) per topic",
)
task_retries = meter.create_histogram(
    "demo__task_retries", unit="1",
    description="Number of retries when completing a task",
)
tasks_in_flight = meter.create_up_down_counter(
    "demo__tasks_in_flight", unit="1",
    description="Number of tasks currently running in parallel per topic",
)

# A two-variable mapping approach is necessary to recursively generate mutually independent root traces (for main and
# call-activity workflows) and still link them together bottom-up
LOCAL_ROOT_VAR = "otelLocalRootTraceContext"     #  Constant per process instance (main or sub)
PARENT_CONTEXT_VAR = "otelParentTraceContext"    # Relevant only for the VERY FIRST task of an instance

class TaskHandler:
    TIMEOUT_1_MINUTE = 60000
    TIMEOUT_5_MINUTES = 3000000

    def __init__(self, handlers_config: dict = None):
        self.log_context = {}
        handler_name = self.__class__.__name__
        self.config_all = handlers_config.get(handler_name, {})

        # IAM client
        self.iam_client = None
        iam_config = worker_config.get_all().get("iam")
        if iam_config is not None and iam_config.get("enabled", False):
            iam_client_id = worker_secrets.get_secret("iam_client_id", None)
            iam_client_secret = worker_secrets.get_secret("iam_client_secret", None)
            token_url = iam_config.get("oidc_token_endpoint_url", None)
            if token_url is not None and iam_client_id is not None and iam_client_secret is not None:
                self.iam_client = IAMClient(
                    token_endpoint_url=token_url, client_id=iam_client_id, client_secret=iam_client_secret
                )

    def execute_wrapper(self, task: ExternalTask, config: dict = None) -> TaskResult:
        topic_name = task.get_topic_name()

        # --- Tracing Setup (None at the start of a run (of an instance), both in Main and Call Activities) ---
        local_root = task.get_variable(LOCAL_ROOT_VAR)

        if local_root:
            # The process instance already has a grouping span? -> just append it
            # Takes effect only in the Call-Activity sub-workflow
            parent_ctx = extract({"traceparent": local_root})
            ctx_token = attach(parent_ctx)
        else:
            # is also None for the first task in a workflow; it is set via mapping when transitioning to a Call activity
            incoming_parent = task.get_variable(PARENT_CONTEXT_VAR)
            links = [] # Is empty for the first workflow task and is only populated for subsequent Call Activity tasks
            if incoming_parent: # Is true starting with the first call activity and stores a link to the grouping span for cross-process trace linking
                remote_ctx = extract({"traceparent": incoming_parent})
                remote_span_ctx = trace.get_current_span(remote_ctx).get_span_context()
                if remote_span_ctx.is_valid:
                    links.append(trace.Link(remote_span_ctx))

            workflow_label = self._get_workflow_label(task)

            # No more `attach(outer_ctx)` -> new standalone trace,
            # connected to the calling process only via a link
            # Root span for grouping and thus a better overview (has no logic of its own)
            with tracer.start_as_current_span(
                    f"Execute:{workflow_label}_workflow",
                    context=Context(),  # Explicitly empty; otherwise, the parent may have been inherited by mistake
                    links=links,    # Links is empty in the main task, but is populated in the Call Activity instance
            ) as group_span:
                carrier = {}
                inject(carrier, context=set_span_in_context(group_span))
                local_root = carrier.get("traceparent")

            parent_ctx = extract({"traceparent": local_root})
            ctx_token = attach(parent_ctx)

        log_context = {
            "WORKER_ID": task.get_worker_id(),
            "TASK_ID": task.get_task_id(),
            "TOPIC_NAME": topic_name,
        }
        try:
            # --- Metric 1: Increment the in-flight counter BEFORE `execute()` runs ---
            tasks_in_flight.add(1, attributes={"topic_name": topic_name})

            with tracer.start_as_current_span(
                f"Execute-{topic_name}",
                attributes={
                    "operaton.task_id": task.get_task_id(),
                    "operaton.topic_name": topic_name,
                    "operaton.process_instance_id": task.get_process_instance_id(),
                },
            ) as span:
                start = time.monotonic()
                try:
                    result = self.execute(task, config or {})

                    # --- Metric 2: Measure Duration (Successful Run) ---
                    task_duration.record(
                        time.monotonic() - start,
                        attributes={"topic_name": topic_name},
                    )

                    # --- Metric 3: Status-Counter ---
                    status = self._infer_result_status(result)
                    task_counter.add(1, attributes={"topic_name": topic_name, "status": status})

                    if getattr(result, "global_variables", None) is None:
                        result.global_variables = {}
                    result.global_variables[LOCAL_ROOT_VAR] = local_root

                    span.set_status(StatusCode.OK)
                    return result
                except Exception as e:
                    # --- Metric 2 (Error Case) + Metric 3 ---
                    task_duration.record(
                        time.monotonic() - start,
                        attributes={"topic_name": topic_name},
                    )
                    task_counter.add(1, attributes={"topic_name": topic_name, "status": "exception"})

                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR)
                    log_with_context(f"Unexpected error: {e}", log_context, log_level="error")
                    raise
        finally:
            # --- Metric 4: Number of retries upon completion (regardless of success or failure) ---
            retries = task._context.get("retries")
            if retries is not None:
                task_retries.record(retries, attributes={"topic_name": topic_name})

            # --- Metric 1: Count down the in-flight counter again ---
            tasks_in_flight.add(-1, attributes={"topic_name": topic_name})

            detach(ctx_token)

    def _infer_result_status(self, result: TaskResult) -> str:
        if getattr(result, "success_state", None) is False:
            if getattr(result, "bpmn_error_code", None):
                return "bpmn_error"
            return "business_failure"
        return "success"

    def _get_workflow_label(self, task: ExternalTask) -> str:
        return task._context.get("processDefinitionKey", task.get_topic_name())

    def execute(self, task: ExternalTask, config: dict = None) -> TaskResult:
        raise NotImplementedError

    def get_config(self, key, default):
        return self.config_all.get(key, default)
