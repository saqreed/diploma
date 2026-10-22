"""Install independent, labeled demo cases through the real API, without resetting data."""
import argparse
from dataclasses import dataclass
from datetime import date
import json
import os
import re
from time import sleep
from urllib.parse import urlparse

import httpx2 as httpx


DAY = 86400
MONTH = 30 * DAY
BLOCKED_RECIPIENT = "Учебный счёт из стоп-листа"
ACCOUNT_A = "Учебный счёт А"
ACCOUNT_B = "Учебный счёт Б"
ACCOUNT_C = "Учебный счёт В"


@dataclass(frozen=True)
class Example:
    code: str
    title: str
    amount: str
    group: str
    expected: str = "APPROVED"
    action: str = "pay"
    recipient: str = ACCOUNT_A
    author: str = "employee"
    receipt: str | None = None
    preparation: str = "approve"
    recipient_scope: str | None = None


def default_series():
    return "VKR2-" + date.today().strftime("%Y%m%d")


def examples():
    return [
        Example("01", "Обычный расход — полный путь", "500", "обычный расход", action="submit", preparation="draft"),
        Example("02", "Получатель в стоп-листе", "850", "проверка получателя", "REJECTED", "submit", BLOCKED_RECIPIENT, preparation="draft"),
        Example("03", "Нормальный получатель — контроль", "850", "проверка получателя", action="submit", preparation="draft"),
        Example("04", "Сочетание риска: сумма и поставщик", "3200", "рискованный поставщик", "REJECTED", "submit", preparation="draft"),
        Example("05", "Та же организация, небольшая сумма", "1200", "рискованный поставщик", action="submit", preparation="draft"),
        Example("06", "Крупный расход: исходное правило", "18000", "крупный расход", "PENDING_REVIEW"),
        Example("07", "Нужны специалист И подтверждение", "5000", "несколько реакций", "PENDING_REVIEW"),
        Example("08", "Запрет сильнее двух других реакций", "8000", "несколько реакций", "REJECTED"),
        Example("09", "Небольшая сумма без ограничений", "1000", "несколько реакций"),
        Example("10", "Чужой сотрудник повторно предъявил чек", "650", "повтор чека", "REJECTED", author="employee2", receipt="DUPLICATE"),
        Example("11", "Другой номер чека — контроль", "650", "повтор чека", author="employee2"),
        Example("12", "Третья выплата за сутки", "300", "частота: три", "REJECTED"),
        Example("13", "Вторая выплата за сутки — контроль", "300", "частота: две"),
        Example("14", "Дробление: три части, два поставщика, 11 500", "2500", "дробление: превышение", "PENDING_REVIEW", recipient_scope="split-high"),
        Example("15", "Три небольшие части: итог 6 500 — контроль", "2500", "дробление: норма", recipient_scope="split-low"),
        Example("16", "Третий уникальный счёт за сутки", "400", "уникальные счета: три", "PENDING_CONFIRMATION", recipient=ACCOUNT_C),
        Example("17", "Знакомый счёт: уникальных осталось два", "400", "уникальные счета: два", recipient=ACCOUNT_B),
        Example("18", "Отклонение и повторная отправка", "1200", "последовательность", "PENDING_REVIEW", preparation="resubmit"),
        Example("19", "Первая отправка без отклонения", "1200", "последовательность"),
        Example("20", "Контрольная выплата найдена", "900", "контрольная выплата: есть"),
        Example("21", "Нет обязательной контрольной выплаты", "900", "контрольная выплата: нет", "PENDING_REVIEW"),
        Example("22", "Рост суммы: раньше 700, теперь 2 200", "2200", "сравнение: рост", "PENDING_CONFIRMATION"),
        Example("23", "Сумма снизилась с 700 до 600", "600", "сравнение: снижение"),
        Example("24", "Новые реквизиты при существующей истории", "750", "новизна: новые", "PENDING_CONFIRMATION", recipient=ACCOUNT_B),
        Example("25", "Прежние реквизиты", "750", "новизна: известные"),
        Example("26", "Истории пока нет — отдельное состояние", "750", "новизна: пусто"),
        Example("27", "Ручное рассмотрение без исключения", "3500", "исключение: обычный", "PENDING_REVIEW"),
        Example("28", "Доверенный поставщик: исключение правила", "3500", "исключение: доверенный"),
        Example("29", "Исключение не отменяет другой запрет", "3500", "исключение: доверенный", "REJECTED", recipient=BLOCKED_RECIPIENT),
        Example("30", "Мелкие выплаты исключены фильтром", "1200", "фильтр: две"),
        Example("31", "Три подходящие выплаты после фильтра", "1200", "фильтр: три", "REJECTED"),
        Example("32", "НЕ: доверенный поставщик исключает риск", "3200", "логика: доверенный", action="submit", preparation="draft"),
        Example("33", "Три сотрудника направляют 11 000 на один счёт", "3000", "общий получатель: три автора", "PENDING_REVIEW", author="accountant", recipient_scope="three-authors"),
        Example("34", "Повторяется один автор: всего два — контроль", "3000", "общий получатель: два автора", author="accountant", recipient_scope="two-authors"),
        Example("35", "Третий новый счёт за десять минут", "400", "быстрая смена: новый", "PENDING_CONFIRMATION", recipient=ACCOUNT_C, recipient_scope="fast-new"),
        Example("36", "Быстрая серия со знакомым счётом — контроль", "400", "быстрая смена: знакомый", recipient=ACCOUNT_B, recipient_scope="fast-known"),
        Example("37", "После отказа изменены сумма и получатель", "1200", "повтор после отказа: изменение", "PENDING_REVIEW", recipient=ACCOUNT_B, preparation="changed_cycle"),
        Example("38", "После отказа параметры прежние — контроль", "900", "повтор после отказа: без изменения", preparation="same_cycle"),
    ]


def history_examples():
    rows = [Example("H10", "Оплаченный оригинал чека", "650", "повтор чека", receipt="DUPLICATE")]
    for code, group, amounts in (
        ("H12", "частота: три", ["300", "300"]),
        ("H13", "частота: две", ["300"]),
        ("H14", "дробление: превышение", ["4500", "4500"]),
        ("H15", "дробление: норма", ["2000", "2000"]),
        ("H30", "фильтр: две", ["500", "500", "1500"]),
        ("H31", "фильтр: три", ["1000", "1000", "500"]),
    ):
        rows.extend(Example(code + str(i), "Предыдущая выплата " + str(i + 1), amount,
                            "дробление: другой поставщик" if code == "H14" and i == 0 else group,
                            recipient_scope={"H14": "split-high", "H15": "split-low"}.get(code))
                    for i, amount in enumerate(amounts))
    for code, group in (("H16", "уникальные счета: три"), ("H17", "уникальные счета: два")):
        rows.extend(Example(code + str(i), "Предыдущий получатель " + str(i + 1), "100", group, recipient=recipient)
                    for i, recipient in enumerate((ACCOUNT_A, ACCOUNT_B)))
    for code, group, amount in (
        ("H20", "контрольная выплата: есть", "1"),
        ("H22", "сравнение: рост", "700"),
        ("H23", "сравнение: снижение", "700"),
        ("H24", "новизна: новые", "100"),
        ("H25", "новизна: известные", "100"),
    ):
        rows.append(Example(code, "Предыдущая успешная выплата", amount, group))
    for code, scope, authors in (("H33", "three-authors", ("employee", "employee2")),
                                  ("H34", "two-authors", ("employee", "employee"))):
        rows.extend(Example(code+str(i), "Расход автора "+author, "4000", "общий получатель: поставщик "+str(i+1),
                            author=author, recipient_scope=scope) for i, author in enumerate(authors))
    for code, group, scope in (("H35", "быстрая смена: новый", "fast-new"),
                               ("H36", "быстрая смена: знакомый", "fast-known")):
        rows.extend(Example(code+str(i), "Предыдущий счёт "+str(i+1), "100", group,
                            recipient=recipient, recipient_scope=scope) for i, recipient in enumerate((ACCOUNT_A, ACCOUNT_B)))
    return rows


def vendor(series, group):
    return f"Демо: {group} [{series}]"


def payload(example, series):
    title = "Предыстория" if example.code.startswith("H") else "Демо"
    return {"title": f"{title} {example.code} — {example.title} [{series}]", "amount": example.amount,
            "recipient": example.recipient + (f" [{series}/{example.recipient_scope}]" if example.recipient_scope else ""), "vendor": vendor(series, example.group),
            "receipt": f"{series}-{example.receipt or example.code}", "purchase_date": date.today().isoformat(), "category": "other"}


def field(name, op, value):
    return {"kind": "field", "field": name, "op": op, "value": value}


def rule_examples(series, list_ids):
    baseline_titles = [payload(row, series)["title"] for row in history_examples()]
    def rule(name, groups, expression, reaction, action="pay", exception=None):
        exclusions = [{"kind": "not", "child": field("vendor", "in", [vendor(series, group) for group in groups])},
                      field("title", "in", baseline_titles)]
        if exception:
            exclusions.append(exception)
        return {"application_id": "demo", "name": f"Демо {series} — {name}", "action": action,
                "expression": expression, "reaction": reaction, "enabled": True,
                "exception": {"kind": "any", "children": exclusions}}
    def history(kind, period=DAY, **values):
        return {"kind": kind, "period_seconds": period, "group_by": ["author", "vendor"],
                "event_types": ["pay"], "statuses": ["SUCCESS"], **values}
    blocked = {"kind": "field", "field": "recipient", "op": "in", "list_id": list_ids["blocked"]}
    risky = {"kind": "field", "field": "vendor", "op": "in", "list_id": list_ids["risky"]}
    trusted = {"kind": "field", "field": "vendor", "op": "in", "list_id": list_ids["trusted"]}
    small = field("amount", "lt", 10000)
    def all_of(*children):
        return {"kind": "all", "children": list(children)}
    def fast_expression(group):
        def fast_history(kind, period=600, **values):
            return history(kind, period, group_by=["author"], filter=field("vendor", "eq", vendor(series, group)), **values)
        return all_of(fast_history("novelty", MONTH, field="recipient", on_empty=False),
                      fast_history("count", include_current=True, op="ge", value=3),
                      fast_history("aggregate", aggregate="unique", field="recipient", include_current=True, op="ge", value=3))
    return [
        rule("Получатель в стоп-листе", ["проверка получателя"], blocked, "BLOCK", "submit"),
        rule("И, ИЛИ, НЕ: сочетание признаков", ["рискованный поставщик", "логика: доверенный"],
             {"kind": "all", "children": [field("amount", "ge", 2500), {"kind": "any", "children": [blocked, risky]},
                                             {"kind": "not", "child": trusted}]}, "BLOCK", "submit"),
        rule("Независимый запрет выплаты получателю", ["исключение: доверенный"], blocked, "BLOCK"),
        rule("Крупный расход свыше 10 000", ["крупный расход"], field("amount", "gt", 10000), "REVIEW"),
        rule("Несколько реакций: рассмотрение", ["несколько реакций"], field("amount", "ge", 4000), "REVIEW"),
        rule("Несколько реакций: подтверждение", ["несколько реакций"], field("amount", "ge", 4000), "CONFIRM"),
        rule("Несколько реакций: запрет", ["несколько реакций"], field("amount", "ge", 7000), "BLOCK"),
        rule("Повтор чека между сотрудниками", ["повтор чека"],
             {**history("duplicate", MONTH), "group_by": ["vendor"], "match_fields": ["receipt", "purchase_date"]}, "BLOCK"),
        rule("Три выплаты сотрудника за 24 часа", ["частота: три", "частота: две"],
             history("count", include_current=True, op="ge", value=3), "BLOCK"),
        rule("Дробление: сумма серии за 24 часа", ["дробление: превышение", "дробление: норма"],
             all_of(small,
                    history("count", group_by=["author", "recipient"], filter=small, include_current=True, op="ge", value=3),
                    history("aggregate", group_by=["author", "recipient"], filter=small, aggregate="sum", field="amount", include_current=True, op="ge", value=10000)), "REVIEW"),
        rule("Три уникальных счёта за 24 часа", ["уникальные счета: три", "уникальные счета: два"],
             history("aggregate", aggregate="unique", field="recipient", include_current=True, op="ge", value=3), "CONFIRM"),
        rule("Отправка, отклонение, повторная отправка", ["последовательность"],
             {**history("sequence", MONTH), "group_by": ["request_id"], "event_types": ["submit", "reject"],
              "sequence": ["submit", "reject", "submit"]}, "REVIEW"),
        rule("Нужна предыдущая контрольная выплата", ["контрольная выплата: есть", "контрольная выплата: нет"],
             history("previous", MONTH, match_fields=["recipient", "vendor"], filter=field("amount", "eq", 1)), "REVIEW"),
        rule("Сумма выросла относительно предыдущей выплаты", ["сравнение: рост", "сравнение: снижение"],
             history("related", MONTH, field="amount", right_field="amount", op="gt"), "CONFIRM"),
        rule("Новый счёт при непустой истории", ["новизна: новые", "новизна: известные", "новизна: пусто"],
             history("novelty", MONTH, field="recipient", on_empty=False), "CONFIRM"),
        rule("Рассмотрение с исключением доверенного поставщика", ["исключение: обычный", "исключение: доверенный"],
             field("amount", "ge", 2000), "REVIEW", exception=field("vendor", "eq", vendor(series, "исключение: доверенный"))),
        rule("Частота: учитываются только выплаты от 1 000", ["фильтр: две", "фильтр: три"],
             history("count", include_current=True, op="ge", value=3, filter=field("amount", "ge", 1000)), "BLOCK"),
        rule("Общий счёт: разные авторы И общая сумма", ["общий получатель: три автора", "общий получатель: два автора"],
             all_of(history("aggregate", group_by=["recipient"], aggregate="unique", field="author", include_current=True, op="ge", value=3),
                    history("aggregate", group_by=["recipient"], aggregate="sum", field="amount", include_current=True, op="ge", value=10000)), "REVIEW"),
        *[rule("Новый счёт И частота И разные счета: "+group, [group], fast_expression(group), "CONFIRM")
          for group in ("быстрая смена: новый", "быстрая смена: знакомый")],
        rule("Повтор после отказа И изменение параметров", ["повтор после отказа: изменение", "повтор после отказа: без изменения"],
             all_of({**history("sequence", MONTH), "group_by": ["request_id"], "event_types": ["submit", "reject"], "sequence": ["submit", "reject", "submit"]},
                    {"kind": "any", "children": [history("related", MONTH, group_by=["request_id"], event_types=["reject"], field="recipient", right_field="recipient", op="ne"),
                                                  history("related", MONTH, group_by=["request_id"], event_types=["reject"], field="amount", right_field="amount", op="gt")]}),
             "REVIEW", exception={"kind": "not", "child": history("count", MONTH, group_by=["request_id"], event_types=["reject"], op="ge", value=1)}),
    ]


class DemoExamplesError(Exception):
    pass


class DemoExamplesClient:
    def __init__(self, url, password):
        target = urlparse(url)
        if target.scheme not in {"http", "https"} or target.hostname not in {"127.0.0.1", "localhost", "backend"} or target.username or target.query or target.fragment:
            raise DemoExamplesError("Для учебных примеров нужен локальный адрес стенда")
        self.url, self.password, self.clients = url.rstrip("/"), password, {}

    def call(self, role, path, body=None, method=None, params=None):
        if role not in self.clients:
            client = httpx.Client(base_url=self.url, trust_env=False, timeout=30, headers={"X-Requested-With": "antifraud-ui"})
            self.clients[role] = client
            result = client.post("/api/auth/login", json={"username": role, "password": self.password})
            if result.status_code != 200:
                raise DemoExamplesError("Не удалось войти учебным аккаунтом " + role)
        for attempt in range(9):
            response = self.clients[role].request(method or ("POST" if body is not None else "GET"), "/api" + path, json=body, params=params)
            try:
                code = response.json().get("code")
            except (ValueError, AttributeError):
                code = None
            if response.status_code != 503 or code != "history_pending" or not isinstance(body, dict) or not body.get("operation_id") or not path.endswith(("/action", "/check")) or attempt == 8:
                break
            # No decision was admitted. Keep the original operation and payload;
            # never retry a restriction, changed context or generic network error.
            sleep(.25)
        if response.status_code != 200:
            raise DemoExamplesError(f"Учебная подготовка: {method or 'request'} {path}, HTTP {response.status_code}")
        return response.json()

    def action(self, row, action, role, step):
        result = self.call(role, "/demo/requests/" + row["id"] + "/action", {
            "action": action, "operation_id": "examples:" + row["id"] + ":" + step, "version": row["version"]})
        if not result["execution"]:
            raise DemoExamplesError("Подготовку учебной предыстории ограничивает правило. Существующие правила не изменены; проверьте карточку заявки.")
        return result["execution"]["request"]

    def close(self):
        for client in self.clients.values():
            client.close()


def install_examples(client, series):
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,24}", series):
        raise DemoExamplesError("Название серии: 1–24 латинских букв, цифр, дефисов или подчёркиваний")
    result = {"series": series, "created_requests": 0, "created_rules": 0, "created_lists": 0, "examples": []}
    def ensure_request(example):
        data = payload(example, series)
        rows = client.call(example.author, "/demo/requests/page", params={"search": data["receipt"], "limit": 100})["items"]
        existing = [r for r in rows if r["author"] == example.author and r["receipt"] == data["receipt"]]
        if existing:
            return min(existing, key=lambda row: (row["created_at"], row["id"])), False
        result["created_requests"] += 1
        initial = {**data, "amount": "900", "recipient": ACCOUNT_A} if example.preparation == "changed_cycle" else data
        return client.call(example.author, "/demo/requests", initial), True
    def prepare(row, example):
        row = client.action(row, "submit", example.author, "submit")
        if example.preparation in {"resubmit", "changed_cycle", "same_cycle"}:
            row = client.action(row, "reject", "manager", "reject")
            if example.preparation == "changed_cycle":
                row = client.call(example.author, "/demo/requests/"+row["id"], payload(example, series), "PUT")
            row = client.action(row, "submit", example.author, "resubmit")
            if example.preparation == "resubmit":
                return row
        return client.action(row, "approve", "manager", "approve")

    # Every historical fact comes from an actual allowed demo action and its outbox.
    # No checks are fabricated as facts, and no existing request is replayed or reset.
    for example in history_examples():
        row, created = ensure_request(example)
        if created:
            row = prepare(row, example)
            client.action(row, "pay", "accountant", "pay")
        elif row["status"] != "PAID":
            raise DemoExamplesError("Предыстория этой серии не завершена. Существующая заявка сохранена; выберите новую серию через --series.")
    for example in examples():
        row, created = ensure_request(example)
        if created and example.preparation != "draft":
            row = prepare(row, example)
        result["examples"].append({"code": example.code, "id": row["id"], "title": row["title"], "author": row["author"],
                                   "status": row["status"], "action": example.action, "expected": example.expected})

    lists = client.call("admin", "/admin/watchlists", params={"application_id": "demo"})
    list_ids = {}
    for key, description, values in (
        ("blocked", "Учебный стоп-лист получателей", [BLOCKED_RECIPIENT, "Второй учебный запрещённый счёт"]),
        ("risky", "Учебные рискованные поставщики", [vendor(series, "рискованный поставщик"), vendor(series, "логика: доверенный")]),
        ("trusted", "Учебные доверенные поставщики", [vendor(series, "логика: доверенный")]),
    ):
        name = f"Демо {series} — {description}"
        existing = next((row for row in lists if row["name"] == name), None)
        if not existing:
            existing = client.call("admin", "/admin/watchlists", {"application_id": "demo", "name": name, "values": values})
            result["created_lists"] += 1
        list_ids[key] = existing["id"]
    saved = client.call("admin", "/admin/rules", params={"application_id": "demo"})
    for rule in rule_examples(series, list_ids):
        if not any(row["name"] == rule["name"] for row in saved):
            client.call("admin", "/admin/rules", rule)
            result["created_rules"] += 1
    return result


def main():
    parser = argparse.ArgumentParser(description="Добавить готовые учебные примеры через API, сохраняя существующие данные")
    parser.add_argument("--url", default=os.environ.get("DIPLOMA_DEMO_EXAMPLES_URL", "http://127.0.0.1:8000"))
    parser.add_argument("--series", default=default_series())
    args = parser.parse_args()
    password = os.environ.get("DIPLOMA_SEED_PASSWORD")
    if not password:
        parser.error("Запустите tools-сервис demo-examples: он передаёт пароль из локального .env")
    client = DemoExamplesClient(args.url, password)
    try:
        result = install_examples(client, args.series)
        print(json.dumps({key: value for key, value in result.items() if key != "examples"}, ensure_ascii=False))
        print(f"Готовы {len(result['examples'])} основных примера. Инструкция: docs/DEMO_WALKTHROUGH.md")
    except DemoExamplesError as error:
        parser.exit(1, str(error) + "\n")
    finally:
        client.close()


if __name__ == "__main__":
    main()
