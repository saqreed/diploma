"""Educational business data only; no real payment information."""
from datetime import date

DEMO_FIELDS = {
    name: {"type": "number" if name in {"amount", "version"} else "string", "source": "API", "required": name != "approver"}
    for name in ("request_id", "amount", "recipient", "author", "receipt", "vendor", "purchase_date", "title", "category", "version", "initiator", "approver")
}
DEMO_CATALOG = {action: {"fields": DEMO_FIELDS} for action in ("submit", "approve", "reject", "pay")}
DEMO_CATALOG["export"] = {"fields": {
    "record_count": {"type": "number", "source": "API", "required": True},
    "initiator": {"type": "string", "source": "API", "required": True},
    "registry_version": {"type": "string", "source": "API", "required": True},
    "registry_snapshot": {"type": "string", "source": "API", "required": True},
}}


def seed_data():
    base = {"author": "employee", "recipient": "Тестовый получатель", "vendor": "Учебный магазин", "purchase_date": date.today().isoformat(),
            "version": 1, "status": "DRAFT", "history": [{"action": "created", "actor": "seed", "version": 1}]}
    return [{**base, "amount": "500.00", "receipt": "DEMO-001", "title": "Обычная учебная заявка"},
            {**base, "amount": "20000.00", "receipt": "DEMO-002", "title": "Крупная сумма: ручная проверка"},
            {**base, "author": "employee2", "amount": "500.00", "receipt": "DEMO-001", "title": "Повтор чека: учебный пример"},
            {**base, "amount": "6000.00", "receipt": "DEMO-SPLIT-1", "title": "Дробление суммы: первая заявка"},
            {**base, "amount": "6000.00", "receipt": "DEMO-SPLIT-2", "title": "Дробление суммы: вторая заявка"}]
