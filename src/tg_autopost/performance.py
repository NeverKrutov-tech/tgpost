import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

# ponytail: SQLite on Render is wiped every deploy, so post metrics live in a
# git-committed JSON file (same pattern as data/published_keys.txt). The DB is
# only a cache for the current process.


class PerformanceStore:
    def __init__(self, path: str) -> None:
        self.path = Path(path)

    def load(self) -> dict:
        if not self.path.exists():
            return {}
        try:
            return json.loads(self.path.read_text(encoding="utf-8"))
        except Exception:
            logger.exception("Failed to read %s", self.path)
            return {}

    def append(self, msg_id: int, metrics: dict) -> None:
        data = self.load()
        data[str(msg_id)] = metrics
        self.save(data)

    def save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            self.path.write_text(
                json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8"
            )
        except Exception:
            logger.exception("Failed to write %s", self.path)

    def channel_effectiveness(self, data: dict | None = None, min_posts: int = 10) -> dict[str, float]:
        data = data if data is not None else self.load()
        by_channel: dict[str, list[float]] = {}
        for m in data.values():
            channel = m.get("channel", "")
            views = int(m.get("views", 0))
            forwards = int(m.get("forwards", 0))
            if not channel or views <= 0:
                continue
            by_channel.setdefault(channel, []).append(forwards / views)
        eff: dict[str, float] = {}
        for channel, rates in by_channel.items():
            if len(rates) < min_posts:
                continue
            eff[channel] = sum(rates) / len(rates)
        if not eff:
            return {}
        if len(eff) > 1:
            sorted_vals = sorted(eff.values())
            median = sorted_vals[len(sorted_vals) // 2]
        else:
            median = next(iter(eff.values()))
        return {ch: (rate / median if median else 1.0) for ch, rate in eff.items()}


def collect_performance(settings, db, store=None) -> int:
    """Заполняет метрики (views/forwards/reactions) для записей performance.json,
    где views ещё 0. msg_id приходят из первичных записей, созданных при
    публикации (см. _record_post_for_pin). Возвращает число обработанных."""
    from .handlers import _api_call

    if store is None:
        store = PerformanceStore("data/performance.json")

    data = store.load()
    collected = 0
    for msg_id_str, metrics in data.items():
        if int(metrics.get("views", 0)) > 0:
            continue  # уже собрано
        try:
            mid = int(msg_id_str)
            resp = _api_call(settings.bot_token, "getMessage", {
                "chat_id": settings.channel_id,
                "message_id": mid,
            }, timeout=10)
            if resp and resp.get("ok"):
                result = resp["result"]
                metrics["views"] = result.get("views", 0)
                metrics["forwards"] = result.get("forwards", 0)
                metrics["reactions"] = len(result.get("reactions") or [])
                data[msg_id_str] = metrics
                collected += 1
        except Exception:
            logger.exception("Failed to collect metrics for msg %s", msg_id_str)
    if collected:
        store.save(data)
    return collected
