/* Purchase Receipt printing follows the Work Order Product QR and QZ Tray flow. */
frappe.ui.form.on("Purchase Receipt", {
  refresh(frm) {
    if (frm.doc.docstatus === 1) {
      frm.add_custom_button(__("Print Label"), () => open_purchase_receipt_labels(frm));
    }
  },
  on_submit(frm) {
    setTimeout(() => open_purchase_receipt_labels(frm), 600);
  }
});

function open_purchase_receipt_labels(frm) {
  frappe.call({
    method: "warehouse_app.overrides.purchase_receipt.get_purchase_receipt_label_data",
    args: { purchase_receipt_name: frm.doc.name },
    freeze: true,
    callback({ message: data }) {
      if (!data || !data.items || !data.items.length) {
        frappe.msgprint(__("Tidak ada item pada Purchase Receipt ini."));
        return;
      }
      show_purchase_receipt_label_dialog(data);
    }
  });
}

function show_purchase_receipt_label_dialog(data) {
  const rows = data.items.map(item => ({ ...item, selected: true, qty: item.max_labels }));
  const dialog = new frappe.ui.Dialog({
    title: __("Cetak Label Item"),
    size: "large",
    fields: [{ fieldtype: "HTML", fieldname: "label_rows" }],
    primary_action_label: __("Ya, Cetak Label"),
    async primary_action() {
      const selections = rows.filter(row => row.selected).map(row => ({
        row: row.row, qty: row.qty, expiry_date: row.expiry_date
      }));
      if (!selections.length || selections.some(row => !Number.isInteger(row.qty) || row.qty < 1)) {
        frappe.msgprint(__("Pilih item dan isi jumlah label yang valid."));
        return;
      }
      if (selections.some(row => !/^\d{4}-\d{2}-\d{2}$/.test(row.expiry_date || ""))) {
        frappe.msgprint(__("Tanggal EXP wajib diisi untuk setiap item yang dicetak."));
        return;
      }
      dialog.get_primary_btn().prop("disabled", true);
      try {
        await print_purchase_receipt_labels(data.purchase_receipt, selections);
        dialog.hide();
      } catch (error) {
        frappe.msgprint({
          title: __("Cetak Label Gagal"),
          message: frappe.utils.escape_html(error.message || String(error)),
          indicator: "red"
        });
      } finally {
        dialog.get_primary_btn().prop("disabled", false);
      }
    }
  });
  const wrapper = dialog.get_field("label_rows").$wrapper;
  const escape = value => frappe.utils.escape_html(String(value ?? ""));
  wrapper.html(`<p>${__("Setiap lembar memakai serial QR sendiri. Cetak ulang menggunakan serial yang sama.")}</p>
    <div class="table-responsive"><table class="table table-bordered">
    <thead><tr><th></th><th>${__("Item Code")}</th><th>${__("Item Name")}</th>
    <th>${__("Batch")}</th><th>${__("RCP")}</th><th>${__("EXP")}</th>
    <th>${__("Jumlah Label")}</th></tr></thead>
    <tbody>${rows.map((row, index) => `<tr data-index="${index}">
      <td><input class="label-check" type="checkbox" checked></td>
      <td>${escape(row.sku)}</td><td>${escape(row.item_name)}</td>
      <td>${escape(row.batch_no || "-")}</td><td>${escape(row.receipt_date || "-")}</td>
      <td><input class="form-control label-exp" type="date" value="${escape(row.expiry_date || "")}" required style="min-width:145px"></td>
      <td><input class="form-control label-qty" type="number" min="1" max="${row.max_labels}" step="1" value="${row.qty}" style="width:100px"></td>
    </tr>`).join("")}</tbody></table></div>`);
  wrapper.find("tr[data-index]").each(function () {
    const row = rows[Number(this.dataset.index)];
    $(this).find(".label-check").on("change", function () { row.selected = this.checked; });
    $(this).find(".label-qty").on("change input", function () {
      const value = Number(this.value);
      row.qty = Number.isInteger(value) && value >= 1 && value <= row.max_labels ? value : NaN;
      this.setCustomValidity(Number.isNaN(row.qty) ? `1–${row.max_labels}` : "");
    });
    $(this).find(".label-exp").on("change input", function () {
      row.expiry_date = this.value;
    });
  });
  dialog.show();
}

function load_qz_tray() {
  if (window.qz) return Promise.resolve(window.qz);
  if (!window.warehouseQzLoading) {
    window.warehouseQzLoading = new Promise((resolve, reject) => {
      const script = document.createElement("script");
      script.src = "/assets/warehouse_app/js/qz-tray.js";
      script.onload = () => window.qz ? resolve(window.qz) : reject(new Error("QZ Tray tidak termuat"));
      script.onerror = () => reject(new Error("Pustaka QZ Tray tidak tersedia"));
      document.head.appendChild(script);
    }).catch(error => { window.warehouseQzLoading = null; throw error; });
  }
  return window.warehouseQzLoading;
}

async function print_purchase_receipt_labels(receipt, selections) {
  const qz = await load_qz_tray();
  qz.security.setCertificatePromise(async () => {
    const response = await fetch(`/api/method/warehouse_app.overrides.qz_signing.certificate?purchase_receipt=${encodeURIComponent(receipt)}`, {
      credentials: "same-origin", cache: "no-store"
    });
    if (!response.ok) throw new Error("Sertifikat QZ Tray belum tersedia atau akses ditolak");
    return (await response.json()).message;
  }, { rejectOnFailure: true });
  qz.security.setSignatureAlgorithm("SHA512");
  qz.security.setSignaturePromise(async request => {
    const response = await fetch("/api/method/warehouse_app.overrides.qz_signing.sign", {
      method: "POST", credentials: "same-origin", cache: "no-store",
      headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token || window.csrf_token || "" },
      body: JSON.stringify({ purchase_receipt: receipt, request })
    });
    if (!response.ok) throw new Error("Gagal menandatangani permintaan QZ Tray");
    return (await response.json()).message;
  });
  if (!qz.websocket.isActive()) await qz.websocket.connect({ retries: 2, delay: 1 });
  const response = await fetch("/api/method/warehouse_app.overrides.purchase_receipt.issue_labels", {
    method: "POST", credentials: "same-origin", cache: "no-store",
    headers: { "Content-Type": "application/json", "X-Frappe-CSRF-Token": frappe.csrf_token || window.csrf_token || "" },
    body: JSON.stringify({ purchase_receipt_name: receipt, selections })
  });
  const body = await response.json();
  if (!response.ok) {
    let detail = "";
    try { detail = JSON.parse(body._server_messages || "[]").map(message => JSON.parse(message).message).join(" "); }
    catch (_error) { /* Frappe did not return structured errors. */ }
    throw new Error(detail || "Gagal mengambil data label");
  }
  const data = body.message;
  const labels = data.items.flatMap(item => item.labels.map(label => ({ ...item, label })));
  if (!labels.length || labels.length !== data.label_count) throw new Error("Jumlah serial label tidak sesuai");
  const printer = await qz.printers.getDefault();
  const jobs = [];
  for (let i = 0; i < labels.length; i += 2) {
    let zpl = "^XA\n^PW800\n^LL160\n";
    zpl += single_purchase_receipt_label_zpl(labels[i], 0, i + 1);
    if (i + 1 < labels.length) zpl += single_purchase_receipt_label_zpl(labels[i + 1], 400, i + 2);
    jobs.push(zpl + "^XZ\n");
  }
  await qz.print(qz.configs.create(printer, { encoding: "UTF-8" }), jobs);
}

function zpl_value(value) {
  return String(value ?? "").replace(/[_^~\\]/g, char => ({
    _: "_5F", "^": "_5E", "~": "_7E", "\\": "_5C"
  })[char]);
}

function short_label_date(value) {
  if (!value) return "-";
  const [year, month, day] = String(value).split("-");
  return `${day}-${month}-${year.slice(-2)}`;
}

function single_purchase_receipt_label_zpl(data, offsetX, sequence) {
  // Shift the entire label content down about 1 mm.
  const x = offsetX - 43;
  const yShift = 8;
  const bold = (x, y, h, w, value, options = "") =>
    `^FO${x},${y}^A0N,${h},${w}${options}^FD${zpl_value(value)}^FS\n` +
    `^FO${x + 1},${y}^A0N,${h},${w}${options}^FD${zpl_value(value)}^FS\n`;
  let zpl = bold(x + 400, 15 + yShift, 18, 18, sequence, "^FB40,1,0,R");
  zpl += `^FO${x + 68},${32 + yShift}^BQN,2,4^FDQA,${zpl_value(data.label.qr_value)}^FS\n`;
  let y = 32 + yShift;
  if (data.item_name_prefix) {
    zpl += bold(x + 192, y, 18, 18, data.item_name_prefix);
    y += 20;
    zpl += bold(x + 192, y, 26, 26, data.item_name_main);
    y += 28;
  } else {
    zpl += bold(x + 192, y, 26, 26, data.item_name_main || data.item_name);
    y += 30;
  }
  zpl += bold(x + 192, y, 21, 21, `SKU : ${data.sku}`);
  zpl += bold(x + 192, y + 24, 21, 21, `RCP : ${short_label_date(data.receipt_date)}`);
  zpl += bold(x + 192, y + 48, 21, 21, `EXP : ${short_label_date(data.expiry_date)}`);
  return zpl;
}
