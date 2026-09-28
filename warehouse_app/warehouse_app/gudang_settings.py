# W11: pengaturan gudang serah terima — UI tipis di atas dua field
# Manufacturing Settings milik production_app:
#   custom_default_handover_source_warehouse (kosong = ikut lot produksi)
#   custom_default_handover_warehouse        (gudang tujuan, wajib saat create)
# production_app tetap satu penulis alur serah terima (R11): page ini hanya
# membaca/menulis NILAI setting-nya; endpoint & validasi di sana tak disentuh.
# W19: field ketiga milik app ini sendiri (Warehouse App Settings) — daftar
# item yang boleh dipakai group request box bersama.

import json

import frappe

SETTING_FIELDS = {
	"source": "custom_default_handover_source_warehouse",
	"target": "custom_default_handover_warehouse",
}
ROLES_SET = ("System Manager", "Gudang Barang Jadi")
GROUP_SETTING = "Warehouse App Settings"


def _require_set_access():
	if not any(role in frappe.get_roles() for role in ROLES_SET):
		frappe.throw(
			frappe._("Hanya System Manager atau Gudang Barang Jadi yang dapat mengubah pengaturan."),
			frappe.PermissionError,
		)


def _clean_warehouse(value, label):
	"""Kosong berarti 'tidak diatur'; selain itu harus Warehouse non-group."""
	value = (value or "").strip()
	if not value:
		return None
	if not frappe.db.exists("Warehouse", value) or frappe.db.get_value(
		"Warehouse", value, "is_group"
	):
		frappe.throw(frappe._("{0} bukan gudang yang valid.").format(label))
	return value


@frappe.whitelist()
def get_handover_settings():
	return {
		"source": frappe.db.get_single_value("Manufacturing Settings", SETTING_FIELDS["source"])
		or "",
		"target": frappe.db.get_single_value("Manufacturing Settings", SETTING_FIELDS["target"])
		or "",
	}


@frappe.whitelist()
def warehouse_options():
	"""Daftar gudang non-group aktif untuk dropdown settings."""
	return frappe.get_all(
		"Warehouse",
		filters={"is_group": 0, "disabled": 0},
		fields=["name"],
		order_by="name",
		pluck="name",
		limit=0,
	)


@frappe.whitelist()
def set_handover_warehouses(source=None, target=None):
	_require_set_access()
	source = _clean_warehouse(source, "Source Warehouse")
	target = _clean_warehouse(target, "Target Warehouse")
	frappe.db.set_single_value("Manufacturing Settings", SETTING_FIELDS["source"], source)
	frappe.db.set_single_value("Manufacturing Settings", SETTING_FIELDS["target"], target)
	frappe.db.commit()
	return {"ok": True, "source": source or "", "target": target or ""}


@frappe.whitelist()
def get_group_items():
	"""Daftar item yang boleh dipakai group request (W19) + peta nama item
	(W20 — UI menampilkan nama, bukan kode saja)."""
	_require_set_access()
	items = frappe.get_all(
		"Warehouse App Group Item",
		filters={"parent": GROUP_SETTING, "parenttype": GROUP_SETTING},
		order_by="idx asc",
		pluck="item",
		limit=0,
	)
	names = {}
	if items:
		rows = frappe.get_all(
			"Item", filters={"name": ["in", items]}, fields=["name", "item_name"], limit=0
		)
		names = {row.name: row.item_name for row in rows}
	return {"items": items, "names": names}


@frappe.whitelist()
def set_group_items(items=None):
	"""Ganti seluruh daftar item grup (replace wholesale). Item wajib ada di
	tabItem; duplikat dibuang; urutan mengikuti input."""
	_require_set_access()
	parsed = items
	if isinstance(parsed, str):
		try:
			parsed = json.loads(parsed)
		except ValueError:
			frappe.throw(frappe._("Format items tidak valid"))
	if parsed is None:
		parsed = []
	if not isinstance(parsed, list):
		frappe.throw(frappe._("Format items tidak valid"))
	ordered = []
	for raw in parsed:
		item = str(raw or "").strip()
		if item and item not in ordered:
			ordered.append(item)
	invalid = [item for item in ordered if not frappe.db.exists("Item", item)]
	if invalid:
		frappe.throw(frappe._("Item tidak ditemukan: {0}").format(", ".join(invalid)))
	doc = frappe.get_doc(GROUP_SETTING)
	doc.set("group_items", [{"item": item} for item in ordered])
	doc.save()
	frappe.db.commit()
	return {"ok": True, "items": ordered}

