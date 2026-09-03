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
    description="Gesamtanzahl der verarbeiteten Operaton-Tasks",
)

task_duration = meter.create_histogram(
    "demo__task_duration_seconds", unit="s",
    description="Dauer der Task-Ausführung (self.execute) pro Topic",
)
task_retries = meter.create_histogram(
    "demo__task_retries", unit="1",
    description="Retry-Anzahl beim Abschluss eines Tasks",
)
tasks_in_flight = meter.create_up_down_counter(
    "demo__tasks_in_flight", unit="1",
    description="Aktuell parallel laufende Tasks pro Topic",
)

# Zwei-Variablen-Mapping-Ansatz ist notwendig, um rekursiv voneinander unabhängige root Traces (für main- und
# call-activity-workflows) zu erzeugen und trotzdem bottom-up miteinander zu verlinken
LOCAL_ROOT_VAR = "otelLocalRootTraceContext"     # stabil PRO Prozessinstanz (Haupt- oder Sub-) --- Wird nach erstem Task gesetzt und behalten?
PARENT_CONTEXT_VAR = "otelParentTraceContext"    # nur beim ALLERERSTEN Task einer Instanz relevant

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

        # --- Tracing-Setup (None zu Beginn eines Durchlaufs(einer Instanz), sowohl im Main als auch in Call-Activities) ---
        local_root = task.get_variable(LOCAL_ROOT_VAR)

        if local_root:
            # Die Prozessinstanz hat schon einen Gruppierungs-Span -> einfach daran anhängen
            # greift erst im Call-Activity Sub-Workflow
            parent_ctx = extract({"traceparent": local_root})
            ctx_token = attach(parent_ctx)
        else:
            # ist bei erstem Task eines Workflows ebenfalls None; wird bei Übergang zu Call-Activity durch Mapping gesetzt
            incoming_parent = task.get_variable(PARENT_CONTEXT_VAR)
            links = [] # beim ersten Workflow-Task leer und wird nur bei folgenden Call-Activity Tasks initial gefüllt
            if incoming_parent: # ist ab erster Call-Activity true und speichert Link zu Gruppierungsspan für Cross-Process-Trace-Linking
                remote_ctx = extract({"traceparent": incoming_parent})
                remote_span_ctx = trace.get_current_span(remote_ctx).get_span_context()
                if remote_span_ctx.is_valid:
                    links.append(trace.Link(remote_span_ctx))

            workflow_label = self._get_workflow_label(task)

            # Kein attach(outer_ctx) mehr -> neuer eigenständiger Trace,
            # nur per Link mit dem aufrufenden Prozess verbunden
            # Root-Span zur Gruppierung und damit besseren Übersicht (hat keine eigene Logik)
            with tracer.start_as_current_span(
                    f"Execute:{workflow_label}_workflow",
                    context=Context(),  # explizit leer, sonst evtl. versehentlich geerbter Parent
                    links=links,    # Links bei main task leer, bei Call-Activity Instanz befüllt
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
            # --- Metrik 4: In-Flight-Counter hochzählen, BEVOR execute() läuft ---
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

                    # --- Metrik 1: Dauer messen (erfolgreicher Durchlauf) ---
                    task_duration.record(
                        time.monotonic() - start,
                        attributes={"topic_name": topic_name},
                    )

                    # --- Metrik 2: Status-Counter ---
                    status = self._infer_result_status(result)
                    task_counter.add(1, attributes={"topic_name": topic_name, "status": status})

                    if getattr(result, "global_variables", None) is None:
                        result.global_variables = {}
                    result.global_variables[LOCAL_ROOT_VAR] = local_root

                    span.set_status(StatusCode.OK)
                    return result
                except Exception as e:
                    # --- Metrik 1 (Fehlerfall) + Metrik 2 ---
                    task_duration.record(
                        time.monotonic() - start,
                        attributes={"topic_name": topic_name},
                    )
                    task_counter.add(1, attributes={"topic_name": topic_name, "status": "exception"})

                    span.record_exception(e)
                    span.set_status(StatusCode.ERROR)
                    log_with_context(f"Unerwarteter Fehler: {e}", log_context, log_level="error")
                    raise
        finally:
            # --- Metrik 3: Retry-Anzahl beim Abschluss (egal ob Erfolg/Fehler) ---
            retries = task._context.get("retries")
            if retries is not None:
                task_retries.record(retries, attributes={"topic_name": topic_name})

            # --- Metrik 4: In-Flight-Counter wieder runterzählen ---
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
