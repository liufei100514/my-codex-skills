#!/usr/bin/env python3
"""EDP 口径探针：从金蝶云星空只读拉原料库存与采购未到货，汇总成吨。

只调用两个接口：ValidateUser + ExecuteBillQuery。零写操作。

用法::

    python erp-material-probe.py                  # 全量（8 万行级，30–90 秒）
    python erp-material-probe.py --limit 50       # 只取前 50 行，验证登录与字段
    python erp-material-probe.py --top 20         # 只看库存最多的 20 个物料
    python erp-material-probe.py --as-of 2026-09-30 --price-db data/cost-center/costs.sqlite3
    python erp-material-probe.py --raw-dir out    # 把两个表单的原始行落盘备查

凭据顺序：Windows 凭据管理器（目标名默认 EDP/Kingdee/InventoryRead）→ 环境变量
EDP_KINGDEE_USERNAME / EDP_KINGDEE_PASSWORD。密码不落盘、不打印。
"""

from __future__ import annotations

import argparse
import ctypes
import json
import os
import sqlite3
import sys
import urllib.parse
import urllib.request
from ctypes import wintypes
from http.cookiejar import CookieJar
from pathlib import Path

DEFAULT_BASE_URL = "https://changlian.ik3cloud.com/K3Cloud"
DEFAULT_ACCOUNT_ID = "5c20de882b6156"
DEFAULT_CREDENTIAL_TARGET = "EDP/Kingdee/InventoryRead"

LOGIN_PATH = "/Kingdee.BOS.WebApi.ServicesStub.AuthService.ValidateUser.common.kdsvc"
QUERY_PATH = "/Kingdee.BOS.WebApi.ServicesStub.DynamicFormService.ExecuteBillQuery.common.kdsvc"

INVENTORY_FORM = "STK_Inventory"
INVENTORY_FIELDS = (
    "FMaterialId.FNumber", "FMaterialId.FName", "FMaterialId.FSpecification",
    "FStockId.FName", "FBaseUnitId.FName", "FBaseQty", "FStockOrgId.FName",
)
INVENTORY_OUTPUT = ("物料编码", "物料名称", "规格型号", "仓库名称", "库存主单位",
                    "库存量(主单位)", "库存组织")

PURCHASE_FORM = "PUR_PurchaseOrder"
PURCHASE_FIELDS = (
    "FBillNo", "FDate", "FSupplierId.FName", "FMaterialId.FNumber", "FMaterialId.FName",
    "FBaseUnitId.FName", "FBaseUnitQty", "FBaseReceiveQty", "FDeliveryDate",
    "FDocumentStatus", "FCancelStatus", "FCloseStatus", "FMRPCloseStatus", "FMrpTerminateStatus",
)
PURCHASE_OUTPUT = ("采购订单号", "采购日期", "供应商", "物料编码", "物料名称", "库存基本单位",
                   "基本单位订单数量", "基本单位已到货数量", "预计到货日期", "单据状态",
                   "取消状态", "整单关闭状态", "业务关闭状态", "终止状态")

TARGET_WAREHOUSES = {"硅基原料仓", "硅基车间仓"}
STOCK_KG_UNITS = {"kg", "千克"}                 # 库存侧口径（注意不含“公斤”）
PURCHASE_KG_UNITS = {"kg", "千克", "公斤"}       # 采购侧口径
PURCHASE_TON_UNITS = {"t", "吨"}


def text(value):
    return str(value or "").strip()


def number(value):
    if value in (None, ""):
        return 0.0
    return float(value)


# --------------------------------------------------------------------------- 凭据

def _credential_via_win32cred(target):
    try:
        import win32cred
    except ImportError:
        return None
    try:
        stored = win32cred.CredRead(target, win32cred.CRED_TYPE_GENERIC)
    except Exception:
        return None
    username = text(stored.get("UserName"))
    blob = stored.get("CredentialBlob") or b""
    if isinstance(blob, bytes):
        try:
            password = blob.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            password = blob.decode("utf-8")
    else:
        password = str(blob)
    return (username, password) if username and password else None


def _credential_via_ctypes(target):
    class CREDENTIALW(ctypes.Structure):
        _fields_ = [("Flags", wintypes.DWORD), ("Type", wintypes.DWORD),
                    ("TargetName", wintypes.LPWSTR), ("Comment", wintypes.LPWSTR),
                    ("LastWritten", wintypes.FILETIME), ("CredentialBlobSize", wintypes.DWORD),
                    ("CredentialBlob", ctypes.POINTER(ctypes.c_ubyte)), ("Persist", wintypes.DWORD),
                    ("AttributeCount", wintypes.DWORD), ("Attributes", ctypes.c_void_p),
                    ("TargetAlias", wintypes.LPWSTR), ("UserName", wintypes.LPWSTR)]

    pointer = ctypes.POINTER(CREDENTIALW)()
    api = ctypes.WinDLL("Advapi32.dll")
    api.CredReadW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                              ctypes.POINTER(ctypes.POINTER(CREDENTIALW))]
    api.CredReadW.restype = wintypes.BOOL
    api.CredFree.argtypes = [ctypes.c_void_p]
    if not api.CredReadW(target, 1, 0, ctypes.byref(pointer)):
        return None
    try:
        stored = pointer.contents
        username = text(stored.UserName)
        blob = ctypes.string_at(stored.CredentialBlob, stored.CredentialBlobSize)
        try:
            password = blob.decode("utf-16-le").rstrip("\x00")
        except UnicodeDecodeError:
            password = blob.decode("utf-8")
        return (username, password) if username and password else None
    finally:
        api.CredFree(pointer)


def resolve_credential(target):
    if os.name == "nt":
        found = _credential_via_win32cred(target) or _credential_via_ctypes(target)
        if found:
            return found, f"Windows 凭据管理器:{target}"
    username = os.environ.get("EDP_KINGDEE_USERNAME", "").strip()
    password = os.environ.get("EDP_KINGDEE_PASSWORD", "")
    if username and password:
        return (username, password), "环境变量 EDP_KINGDEE_*"
    raise SystemExit("KINGDEE_CREDENTIAL_NOT_CONFIGURED：Windows 凭据管理器与环境变量都没有可用凭据")


# --------------------------------------------------------------------------- 传输

class K3Transport:
    def __init__(self, base_url, timeout=90):
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout
        self.opener = urllib.request.build_opener(
            urllib.request.ProxyHandler({})
            if "127.0.0.1" in self.base_url else urllib.request.ProxyHandler(),
            urllib.request.HTTPCookieProcessor(CookieJar()),
        )

    def post(self, path, payload):
        form = payload if "AuthService.ValidateUser" in path else {
            "data": json.dumps(payload, ensure_ascii=False)}
        request = urllib.request.Request(
            self.base_url + path,
            data=urllib.parse.urlencode(form).encode("utf-8"),
            headers={"Content-Type": "application/x-www-form-urlencoded; charset=UTF-8",
                     "User-Agent": "EDP-Material-Probe/1.0"},
            method="POST",
        )
        with self.opener.open(request, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8-sig"))


def login(transport, account_id, credential):
    username, password = credential
    result = transport.post(LOGIN_PATH, {"acctID": account_id, "username": username,
                                         "password": password, "lcid": 2052})
    ok = isinstance(result, dict) and (
        result.get("IsSuccessByAPI") is True or result.get("LoginResultType") == 1)
    if not ok:
        message = result.get("Message") if isinstance(result, dict) else result
        raise SystemExit(f"KINGDEE_LOGIN_FAILED: {message}")
    return True


def query(transport, form_id, fields, output_keys, filter_string, order_string, limit, max_rows):
    rows, start = [], 0
    while True:
        payload = {"FormId": form_id, "FieldKeys": ",".join(fields),
                   "FilterString": filter_string, "OrderString": order_string,
                   "TopRowCount": 0, "StartRow": start, "Limit": limit}
        result = transport.post(QUERY_PATH, payload)
        if not isinstance(result, list):
            raise SystemExit(f"{form_id} 返回结构异常: {str(result)[:300]}")
        if not result:
            break
        for values in result:
            if not isinstance(values, list) or len(values) != len(output_keys):
                raise SystemExit(f"{form_id} 字段与预期不符（期望 {len(output_keys)} 列，实际 "
                                 f"{len(values) if isinstance(values, list) else '?'} 列）")
            rows.append(dict(zip(output_keys, values)))
        if max_rows and len(rows) >= max_rows:
            return rows[:max_rows]
        if len(result) < limit:
            break
        start += len(result)
    return rows


# --------------------------------------------------------------------------- 口径

def aggregate_stock(inventory_rows):
    """两仓合计 → {编码: 吨}；非目标仓/非 kg 单位跳过。"""
    kg_by_code, meta = {}, {}
    for row in inventory_rows:
        code = text(row.get("物料编码"))
        warehouse = text(row.get("仓库名称"))
        unit = text(row.get("库存主单位"))
        if not code or warehouse not in TARGET_WAREHOUSES or unit not in STOCK_KG_UNITS:
            continue
        kg_by_code[code] = kg_by_code.get(code, 0.0) + number(row.get("库存量(主单位)"))
        meta.setdefault(code, {"物料名称": text(row.get("物料名称")),
                               "规格型号": text(row.get("规格型号"))})
    return {code: kg / 1000 for code, kg in kg_by_code.items()}, meta


def _to_tons(value, unit):
    """支持 kg/千克/公斤 → 吨、t/吨 → 吨；其它单位返回 None（由调用方决定跳过还是中止）。"""
    normalized = text(unit).lower()
    if normalized in PURCHASE_KG_UNITS:
        return value / 1000
    if normalized in PURCHASE_TON_UNITS:
        return value
    return None


def aggregate_incoming(purchase_rows, purchase_year, tracked=None, strict=False):
    """台账内物料遇到不支持单位 → 中止（宁可停更）；台账外 → 计入 unsupported 并跳过。"""
    by_code, excluded, unsupported = {}, 0, []
    for row in purchase_rows:
        code = text(row.get("物料编码"))
        if not code:
            continue
        if tracked and code not in tracked:
            continue
        if text(row.get("采购日期")).replace("/", "-")[:4] != str(purchase_year):
            excluded += 1
            continue
        ordered = max(number(row.get("基本单位订单数量")), 0.0)
        received = max(number(row.get("基本单位已到货数量")), 0.0)
        remaining = max(ordered - received, 0.0)
        unit = text(row.get("库存基本单位"))
        tons = _to_tons(remaining, unit)
        if tons is None:
            if strict or (tracked and code in tracked):
                raise SystemExit(f"KINGDEE_PURCHASE_UNIT_UNSUPPORTED: {code} {unit or 'EMPTY'}")
            unsupported.append({"物料编码": code, "单位": unit, "剩余数量": remaining})
            continue
        if tons <= 1e-9:
            continue
        bucket = by_code.setdefault(code, {"在途吨": 0.0, "订单号": set(), "供应商": set(),
                                           "最早到货": ""})
        bucket["在途吨"] += tons
        bill = text(row.get("采购订单号"))
        if bill:
            bucket["订单号"].add(bill)
        supplier = text(row.get("供应商"))
        if supplier:
            bucket["供应商"].add(supplier)
        delivery = text(row.get("预计到货日期")).replace("/", "-")[:10]
        if delivery and (not bucket["最早到货"] or delivery < bucket["最早到货"]):
            bucket["最早到货"] = delivery
    return by_code, excluded, unsupported


def load_price_state(db_path, as_of):
    """按 (effective, id) 回放批次，得到 as_of 当天有效的价格。"""
    if not db_path or not Path(db_path).exists():
        return None
    with sqlite3.connect(db_path) as db:
        db.row_factory = sqlite3.Row
        rows = db.execute(
            "SELECT * FROM batches WHERE effective<=? ORDER BY effective,id", (as_of,)).fetchall()
    prices, revision = {}, 0
    for row in rows:
        payload = json.loads(row["payload"])
        revision = max(revision, row["id"])
        for item in payload.get("prices", []):
            prices[item["materialCode"]] = {"unitPrice": item["unitPrice"],
                                            "kind": item.get("kind", "purchase"),
                                            "effectiveDate": payload.get("effectiveDate")}
    return {"asOf": as_of, "revision": revision, "prices": prices}


# --------------------------------------------------------------------------- 输出

def main(argv=None):
    parser = argparse.ArgumentParser(description="EDP 原料数量与单价口径探针（只读）")
    parser.add_argument("--base-url", default=os.environ.get("EDP_KINGDEE_BASE_URL", DEFAULT_BASE_URL))
    parser.add_argument("--account-id", default=os.environ.get("EDP_KINGDEE_ACCOUNT_ID", DEFAULT_ACCOUNT_ID))
    parser.add_argument("--credential-target", default=DEFAULT_CREDENTIAL_TARGET)
    parser.add_argument("--purchase-year", type=int, default=2026)
    parser.add_argument("--limit", type=int, default=2000, help="单页行数（≤2000）")
    parser.add_argument("--max-rows", type=int, default=0, help="最多取多少行（0=全量）")
    parser.add_argument("--top", type=int, default=15)
    parser.add_argument("--as-of", default="", help="价格生效日 YYYY-MM-DD")
    parser.add_argument("--price-db", default="", help="costs.sqlite3 路径")
    parser.add_argument("--raw-dir", default="", help="把原始行落盘到该目录")
    parser.add_argument("--json", action="store_true", help="输出 JSON 而不是表格")
    parser.add_argument("--tracked-codes", default="",
                        help="台账 JSON（snapshot.json 或 [{erpMaterialCode}...]），只统计台账内物料")
    parser.add_argument("--strict", action="store_true",
                        help="遇到不支持的计量单位直接中止（等同于生产链路的 fail-closed）")
    args = parser.parse_args(argv)

    if not 1 <= args.limit <= 2000:
        raise SystemExit("--limit 必须在 1..2000 之间")

    credential, source = resolve_credential(args.credential_target)
    transport = K3Transport(args.base_url)
    login(transport, args.account_id, credential)

    inventory_rows = query(transport, INVENTORY_FORM, INVENTORY_FIELDS, INVENTORY_OUTPUT,
                           "", "FMaterialId.FNumber ASC", args.limit, args.max_rows)
    purchase_filter = ("FDocumentStatus='C' and FCancelStatus='A' "
                       "and FCloseStatus='A' and FMRPCloseStatus='A' and FMrpTerminateStatus='A' "
                       f"and FDate>='{args.purchase_year}-01-01' and FDate<'{args.purchase_year + 1}-01-01'")
    purchase_rows = query(transport, PURCHASE_FORM, PURCHASE_FIELDS, PURCHASE_OUTPUT,
                          purchase_filter, "FBillNo ASC,FMaterialId.FNumber ASC",
                          args.limit, args.max_rows)

    tracked = None
    if args.tracked_codes:
        payload = json.loads(Path(args.tracked_codes).read_text(encoding="utf-8-sig"))
        if isinstance(payload, dict):
            records = (payload.get("inventory") or {}).get("records") or []
        elif isinstance(payload, list):
            records = payload
        else:
            records = []
        tracked = {text(row.get("erpMaterialCode")) for row in records if isinstance(row, dict)}
        tracked.discard("")
        if not tracked:
            raise SystemExit("台账文件里没有 erpMaterialCode，检查是否传了 snapshot.json")
    stock_tons, meta = aggregate_stock(inventory_rows)
    if tracked:
        # 与台账对齐：台账里 0 库存 0 在途的物料也要出现（平台快照保留全部台账行）
        stock_tons = {code: stock_tons.get(code, 0.0) for code in tracked}
    incoming, excluded, unsupported = aggregate_incoming(
        purchase_rows, args.purchase_year, tracked=tracked, strict=args.strict)
    total_stock = round(sum(stock_tons.values()), 6)
    total_incoming = round(sum(item["在途吨"] for item in incoming.values()), 6)

    price_state = load_price_state(args.price_db, args.as_of) if (args.price_db and args.as_of) else None

    if args.raw_dir:
        out = Path(args.raw_dir)
        out.mkdir(parents=True, exist_ok=True)
        (out / "kingdee-inventory-rows.json").write_text(
            json.dumps(inventory_rows, ensure_ascii=False, indent=1), encoding="utf-8")
        (out / "kingdee-purchase-rows.json").write_text(
            json.dumps(purchase_rows, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"原始行已落盘: {out}")

    summary = {
        "credentialSource": source,
        "accountId": args.account_id,
        "inventoryRowCount": len(inventory_rows),
        "purchaseRowCount": len(purchase_rows),
        "purchaseLinesExcludedOutOfYear": excluded,
        "targetMaterialCount": len(stock_tons),
        "currentStockTons": total_stock,
        "incomingTons": total_incoming,
        "materialsWithIncoming": sum(1 for item in incoming.values() if item["在途吨"] > 0),
        "unsupportedUnitLines": len(unsupported),
        "unsupportedUnits": unsupported[:20],
        "calculation": "stock=Σ(两仓 kg)/1000 ; incoming=FBaseUnitQty-FBaseReceiveQty",
    }
    if price_state is not None:
        summary["price"] = {"asOf": price_state["asOf"], "revision": price_state["revision"],
                            "materialCount": len(price_state["prices"]),
                            "basis": "含税元/kg"}

    if args.json:
        detailed = {
            "summary": summary,
            "materials": [
                {"物料编码": code, "物料名称": meta.get(code, {}).get("物料名称", ""),
                 "当前库存吨": round(stock_tons.get(code, 0.0), 6),
                 "在途吨": round(incoming.get(code, {}).get("在途吨", 0.0), 6),
                 **({"含税单价元每kg": price_state["prices"][code]["unitPrice"],
                     "价格生效日": price_state["prices"][code]["effectiveDate"]}
                    if price_state and code in price_state["prices"] else {})}
                for code in sorted(set(stock_tons) | set(incoming))
            ],
        }
        print(json.dumps(detailed, ensure_ascii=False, indent=1))
        return 0

    print("=" * 78)
    print(f"凭据来源        : {source}")
    print(f"账套            : {args.account_id}")
    print(f"库存行数        : {len(inventory_rows)}   采购行数: {len(purchase_rows)}"
          f"（跨年剔除 {excluded} 行）")
    print(f"目标仓物料数    : {len(stock_tons)}")
    print(f"当前库存合计    : {total_stock:,.3f} 吨（硅基原料仓 + 硅基车间仓，仅 kg 计量）")
    print(f"采购未到货合计  : {total_incoming:,.3f} 吨（{summary['materialsWithIncoming']} 个物料有在途）")
    if unsupported:
        print(f"跳过非 kg/吨 计量 : {len(unsupported)} 行，例："
              + ", ".join(f"{u['物料编码']}({u['单位']})" for u in unsupported[:5]))
    if price_state is not None:
        print(f"价格库          : 版本 {price_state['revision']}，{price_state['asOf']} 有效 "
              f"{len(price_state['prices'])} 个物料，口径 含税元/kg")
    print("=" * 78)

    ranked = sorted(set(stock_tons) | set(incoming),
                    key=lambda c: -(stock_tons.get(c, 0.0) + incoming.get(c, {}).get("在途吨", 0.0)))
    header = f"{'物料编码':<14}{'当前库存(吨)':>14}{'在途(吨)':>12}{'含税单价':>12}  物料名称"
    print(header)
    print("-" * 78)
    for code in ranked[:max(args.top, 1)]:
        price_text = "—"
        if price_state and code in price_state["prices"]:
            price_text = f"{price_state['prices'][code]['unitPrice']:.4f}"
        name = meta.get(code, {}).get("物料名称", "")
        print(f"{code:<14}{stock_tons.get(code, 0.0):>14,.3f}"
              f"{incoming.get(code, {}).get('在途吨', 0.0):>12,.3f}{price_text:>12}  {name}")
    print("-" * 78)
    print("口径：当前库存=两仓合计/1000；在途=FBaseUnitQty-FBaseReceiveQty（仅当年、五状态位过滤）")
    print("提醒：在途不是现货，缺口与到货后净缺口要分开看；缺价物料不按 0 元计算")
    return 0


if __name__ == "__main__":
    sys.exit(main())
