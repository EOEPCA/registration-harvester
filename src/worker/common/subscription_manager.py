from flowable.external_worker_client import ExternalWorkerSubscription


class SubscriptionManager:
    """
    Diese Klassen-Implementierung sorgt dafür, dass nur eine Instanz der Klasse SubscriptionManager existiert.
    Wenn versucht wird, zusätzlich eine neue Instanz zu erstellen,
    wird immer die zu Beginn erstellte Instanz zurückgegeben. Auf diese Weise verhält sich das SubscriptionManagerObjekt
    wie eine globale Variable, kann aber Vorteile von OOP nutzen (siehe Singleton Class).
    """

    # Statische Klassenvariable, die die einzige Instanz der Klasse speichert
    _instance = None

    # __new__ wird aufgerufen und dient zur Erstellung einer neuen Instanz der Klasse
    def __new__(cls, *args, **kwargs):
        # Prüfen, ob bereits eine Instanz der Klasse existiert. Überprüfung kann aber auch
        # an get_instance() delegiert werden, da SubscriptionManager() nicht zum Instanziieren
        # verwendet werden sollte (best practice)
        if not cls._instance:
            # Wenn keine Instanz existiert, wird eine neue erstellt
            cls._instance = super(SubscriptionManager, cls).__new__(cls, *args, **kwargs)
            # Initialisieren eines leeren Dictionaries für Abonnements
            cls._instance._subscriptions = {}
        # Gibt die einzige Instanz zurück (entweder eine neue oder die bereits existierende)
        return cls._instance

    @classmethod
    def get_instance(cls):
        # Gibt die Singleton-Instanz von SubscriptionManager zurück und instanziiert sie vorher, falls nötig.
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def add_subscription(self, topic: str, worker_id: str, subscription: ExternalWorkerSubscription, timestamp: str):
        # Erstelle einen neuen Key für das Topic, falls es noch nicht existiert
        if topic not in self._subscriptions:
            self._subscriptions[topic] = {}

        if worker_id not in self._subscriptions[topic]:
            # Füge die Subscription für die gegebene worker_id unter dem jeweiligen Topic hinzu
            self._subscriptions[topic][worker_id] = {"sub_obj": subscription, "jobs_done": 0, "start_time": timestamp}

    def remove_subscription(self, topic: str, worker_id: str):
        # Überprüfen, ob zu löschender Worker existiert und ihn dann löschen
        if self.worker_exists(topic, worker_id):
            # Worker aus manager löschen
            subscription = self._subscriptions[topic].pop(worker_id)
            subscription["sub_obj"].unsubscribe()
            return True
        return False

    def worker_exists(self, topic: str, worker_id: str):
        # checkt für entsprechenden Topic, ob ein gegebener Worker exisitert
        return topic in self._subscriptions and worker_id in self._subscriptions[topic]

    def _count_subscriptions(self):
        # zählt die subscriptions über die subscribed worker ids (keys)
        all_subs = set(key for d in self._subscriptions.values() for key in d.keys())
        return len(all_subs)

    def get_subscription_objects(self):
        # gibt ein Array mit allen Subscription-Objects des Managers zurück
        return [worker_id["sub_obj"] for topic in self._subscriptions.values() for worker_id in topic.values()]

    def increment_job(self, current_worker):
        # zählt "jobs_done"-Variable des jeweiligen Workerdictionaries um eins nach oben
        current_topic = current_worker.split("_")[1]
        if self.worker_exists(current_topic, current_worker):
            self._subscriptions[current_topic][current_worker]["jobs_done"] += 1

    def get_subscription_info(self):
        # erstellt auf Basis der im Manager gespeicherten Worker-Infos ein Output Dictionary
        result_dict = {
            topic: {
                worker_id: {"jobs_done": worker_data["jobs_done"], "start_time": worker_data["start_time"]}
                for worker_id, worker_data in workers.items()
            }
            for topic, workers in self._subscriptions.items()
        }
        count_dict = {"worker currently working": self._count_subscriptions()}
        return {**count_dict, **result_dict}
