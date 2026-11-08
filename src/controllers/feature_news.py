"""Track newly introduced controls for three days after an update."""
import json
import time

from src.controllers.settings import Settings

NEW_LIFETIME = 3 * 24 * 60 * 60


class FeatureNews:
    _instance = None

    @classmethod
    def instance(cls):
        if cls._instance is None:
            cls._instance = cls()
        return cls._instance

    def __init__(self):
        from src.tweaks.daemon_descriptions import DAEMON_DESCRIPTIONS
        from src.tweaks.daemons_tweak import DANGEROUS_KEYS, INTERFACE_KEYS, Daemon
        from src.tweaks.registry import SPECS_BY_ID
        self.controls = {
            'tweak:' + spec.id.name: {'title': spec.title, 'kind': spec.kind.value,
                                      'description': spec.description}
            for spec in SPECS_BY_ID.values()}
        for daemon in Daemon:
            if not set(daemon.value).intersection(INTERFACE_KEYS) or set(daemon.value).intersection(DANGEROUS_KEYS):
                continue
            self.controls['daemon:' + daemon.name] = {
                'title': daemon.name, 'kind': 'daemon',
                'description': DAEMON_DESCRIPTIONS.get(daemon.name, '')}
        store = Settings()
        try:
            state = json.loads(store.value('feature_news_v1', '{}', type=str))
            if not isinstance(state, dict):
                state = {}
        except (ValueError, TypeError):
            state = {}
        known = state.get('known')
        previous = state.get('introduced', {})
        previous = previous if isinstance(previous, dict) else {}
        now = time.time()
        self.introduced = {key: stamp for key, stamp in previous.items()
                           if key in self.controls and isinstance(stamp, (float, int))
                           and 0 <= now - stamp < NEW_LIFETIME}
        if isinstance(known, list):
            for key in self.controls.keys() - {key for key in known if isinstance(key, str)}:
                self.introduced[key] = now
        announced = state.get('announced', [])
        self.announced = {key for key in announced if isinstance(key, str)} if isinstance(announced, list) else set()
        self._save()

    def _save(self):
        store = Settings()
        store.setValue('feature_news_v1', json.dumps({
            'known': sorted(self.controls), 'introduced': self.introduced,
            'announced': sorted(self.announced.intersection(self.introduced))}))
        store.sync()

    def remaining(self, key):
        return max(0, self.introduced.get(key, 0) + NEW_LIFETIME - time.time())

    def recent(self):
        return [(key, self.controls[key]) for key in self.introduced if self.remaining(key)]

    def has_unseen(self):
        return any(key not in self.announced for key, _ in self.recent())

    def acknowledge(self):
        self.announced.update(key for key, _ in self.recent())
        self._save()
