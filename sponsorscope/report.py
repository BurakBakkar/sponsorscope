from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class RunReport:
    started_at: str
    finished_at: str | None = None
    sources: dict[str, dict] = field(default_factory=dict)
    ats: dict[str, dict] = field(default_factory=dict)

    def source(self, name: str, status: str, **info) -> None:
        self.sources[name] = {"status": status, **info}

    def board_summary(self, ats: str, **info) -> None:
        self.ats[ats] = info

    def warnings(self) -> list[str]:
        out = []
        for name, info in self.sources.items():
            if info["status"] in ("failed", "blocked"):
                out.append(f"{name}: {info['status']} ({info.get('error', '')})")
        for ats, info in self.ats.items():
            if info.get("outage"):
                out.append(f"{ats}: outage, {info['failed'] + info['not_found']} of {info['boards']} boards failed; nothing deactivated")
            elif info.get("failed"):
                out.append(f"{ats}: {info['failed']} of {info['boards']} boards failed")
        return out

    def to_dict(self) -> dict:
        return asdict(self)
