// W9: request serah terima ala-gudang. UI bicara bahasa gudang
// (adonan ke + nama item); pembuatan/pembatalan MR memanggil endpoint
// production_app (create_request/cancel_request) — satu penulis ringkasan
// WO, pola sama dengan aksi papan W4 yang memanggil mapper native erpnext.
// Validasi box (kg + jumlah, harus tepat expected units) andalkan server:
// atomic, fail-honest, pesan errornya langsung tampil sebagai toast.
//
// Revisi umpan balik user: (1) tabel checklist — pilih satu/beberapa WO,
// satu aksi "Buat Request" (dialog alokasi Box per baris, prefilled jumlah
// = hasil WO); (2) panel filter ala list view ERPNext: baris
// [Field][operator][Nilai] + Tambah Filter — field dibatasi whitelist
// server (filter_fields), field Item virtual dicocokkan via nama/kode item.
// W19: group request — pilih ≥2 WO satu item yang terdaftar grup, satu aksi
// "Create Group Request" dengan box BERSAMA (K box utk N WO) lewat endpoint
// create_group_request/cancel_group_request production_app.

// state filter modul-level (satu instance page per sesi)
let WZRQ_FILTERS = []; // [{field, operator, value(array utk between)}]
let WZRQ_FIELD_META = null;
let WZRQ_VISIBLE = null; // key kolom terlihat (persist di localStorage)
let WZRQ_QTY_UOM = null; // uom kolom Qty (persist di localStorage)

frappe.pages['gudang_request'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Handover Requests'),
		single_column: true,
	});

	const $main = $(wrapper).find('.layout-main');
	// .layout-main Desk v16 = flex row: semua konten wajib dibungkus SATU
	// root full-width agar tidak menjadi kolom di samping tabel.
	$main.html(`
		<div class="wzrq-root">
		<div class="wzrq-toolbar">
			<input class="form-control wzrq-search" type="text"
				placeholder="${__('Search batch, item, or work order...')}" />
			<button class="btn btn-default wzrq-filter-btn">
				<svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><polygon points="22 3 2 3 10 12.46 10 19 14 21 14 12.46 22 3"/></svg>
				${__('Filter')}
				<span class="wzrq-filter-count"></span>
			</button>
			<button class="btn btn-default wzrq-refresh">${__('Refresh')}</button>
			<div class="wzrq-bulk">
				<select class="form-control wzrq-uom" title="${__('Qty unit')}"></select>
				<span class="wzrq-bulk-count text-muted"></span>
				<button class="btn btn-primary wzrq-bulk-request" disabled>${__('Create Request')}</button>
				<button class="btn btn-default wzrq-bulk-clear" style="display:none">${__('Clear')}</button>
			</div>
			<div class="wzrq-filter-pop" style="display:none">
				<div class="wzrq-filter-rows"></div>
				<div class="wzrq-filter-foot">
					<button class="btn btn-link wzrq-filter-add">+ ${__('Add Filter')}</button>
					<button class="btn btn-link text-muted wzrq-filter-clearall">${__('Clear All Filters')}</button>
				</div>
			</div>
		</div>
		<div class="wzrq-table-wrap">
			<table class="wzrq-table">
				<thead>
					<tr>
						<th class="wzrq-col-check"><input type="checkbox" class="wzrq-check-all" aria-label="${__('Select all')}" /></th>
						<th class="wzrq-col-adonan">${__('Batch')}</th>
						<th>${__('Item')}</th>
						<th class="wzrq-col-qty">${__('Qty')}</th>
						<th class="wzrq-col-wo">${__('Work Order')}</th>
						<th class="wzrq-col-status">${__('Status')}</th>
						<th class="wzrq-col-aksi"></th>
					</tr>
				</thead>
				<tbody></tbody>
			</table>
			<div class="wzrq-cols-pop" style="display:none"></div>
			<div class="wzrq-empty text-muted" style="display:none">
				${__('No matching Work Orders. Try a different search or clear the filters.')}
			</div>
			<div class="wzrq-foot" style="display:none">
				<span class="wzrq-count text-muted"></span>
				<button class="btn btn-default btn-sm wzrq-more-btn" style="display:none">${__('Load more')}</button>
			</div>
		</div>
		<button class="btn btn-default wzrq-tweak-btn" title="${__('Display settings')}">
			<svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg>
		</button>
		<div class="wzrq-tweak-panel" style="display:none">
			<div class="wzrq-tweak-label">${__('Density')}</div>
			<div class="btn-group wzrq-density" role="group">
				<button class="btn btn-default btn-sm wzrq-den-comfort">${__('Comfort')}</button>
				<button class="btn btn-default btn-sm wzrq-den-compact">${__('Compact')}</button>
			</div>
		</div>
		</div>
	`);

	const $main_page = $(wrapper);
	const $search = $main.find('.wzrq-search');
	const selected = new Set();
	let apply_timer = null;

	function current_search() {
		return $search.val() || '';
	}

	// opts.append: tombol Load more — ambil halaman berikutnya (offset =
	// baris termuat) lalu tempelkan; tanpa append hasil menggantikan baris.
	function load(opts) {
		const append = !!(opts && opts.append);
		const offset = append ? wzrq_rows($main_page).length : 0;
		if (append) {
			$main.find('.wzrq-more-btn').prop('disabled', true);
		}
		frappe.call({
			method: 'warehouse_app.warehouse_app.gudang_request.requestable_work_orders',
			args: {
				search: current_search(),
				filters: JSON.stringify(active_filters()),
				limit_start: offset,
			},
			freeze: !append,
			freeze_message: __('Loading Work Orders...'),
		}).then(
			(r) => {
				const fetched = (r.message && r.message.length && r.message) || [];
				$main_page.data('wzrq_last_fetch', fetched.length);
				wzrq_render($main_page, append ? wzrq_rows($main_page).concat(fetched) : fetched);
				$main.find('.wzrq-more-btn').prop('disabled', false);
			},
			() => $main.find('.wzrq-more-btn').prop('disabled', false)
		);
	}

	function apply_soon() {
		clearTimeout(apply_timer);
		apply_timer = setTimeout(() => {
			wzrq_collect_rows($main_page);
			wzrq_update_filter_count($main_page);
			load();
		}, 300);
	}

	function reload() {
		selected.clear();
		load();
	}

	// --- interaksi tabel ---
	$main.on('click', '.wzrq-check', function (e) {
		e.stopPropagation();
		const wo = $(this).closest('tr').attr('data-wo');
		if (this.checked) {
			selected.add(wo);
		} else {
			selected.delete(wo);
		}
		wzrq_update_bulk($main_page, selected);
	});

	$main.on('click', '.wzrq-row', function (e) {
		if ($(e.target).closest('button, input, a').length) {
			return;
		}
		const wo = $(this).attr('data-wo');
		if (!wzrq_rows($main_page).some((r) => r.name === wo && !r.request_active && !r.request_shipped)) {
			return;
		}
		if (selected.has(wo)) {
			selected.delete(wo);
		} else {
			selected.add(wo);
		}
		$(this).find('.wzrq-check').prop('checked', selected.has(wo));
		wzrq_update_bulk($main_page, selected);
	});

	$main.on('click', '.wzrq-cancel', function () {
		const $btn = $(this);
		// W19: anggota grup — batal SELURUH grup via cancel_group_request
		if ($btn.attr('data-plan')) {
			cancel_group_request($btn.attr('data-plan'), Number($btn.attr('data-size')) || 0, reload);
		} else {
			cancel_request($btn.attr('data-mr'), reload);
		}
	});

	$main.on('change', '.wzrq-check-all', function () {
		const rows = wzrq_rows($main_page).filter((r) => !r.request_active && !r.request_shipped);
		rows.forEach((r) => (this.checked ? selected.add(r.name) : selected.delete(r.name)));
		$main.find('.wzrq-row').each(function () {
			$(this).find('.wzrq-check').prop('checked', selected.has($(this).attr('data-wo')));
		});
		wzrq_update_bulk($main_page, selected);
	});

	// --- aksi massal ---
	$main.on('click', '.wzrq-bulk-request', () => {
		// W19: seleksi ≥2 WO satu item grup -> dialog box BERSAMA, bukan per WO
		const group_rows = $main_page.data('wzrq_group');
		if (group_rows && group_rows.length) {
			group_dialog(group_rows, reload);
			return;
		}
		const wos = wzrq_rows($main_page).filter((r) => selected.has(r.name));
		if (wos.length) {
			bulk_dialog(wos, reload);
		}
	});

	$main.on('click', '.wzrq-bulk-clear', () => {
		selected.clear();
		$main.find('.wzrq-check').prop('checked', false);
		wzrq_update_bulk($main_page, selected);
	});

	// ganti uom kolom Qty: preferensi tampilan saja — render ulang tanpa fetch.
	// tbody dirender ulang polos: kosongkan `selected` agar tidak basi
	// (counter/bulk jalan-jalan dengan WO yang checkboxnya sudah hilang).
	$main.on('change', '.wzrq-uom', function () {
		selected.clear();
		WZRQ_QTY_UOM = this.value;
		wzrq_store('wzrq_qty_uom', WZRQ_QTY_UOM);
		wzrq_render($main_page, wzrq_rows($main_page));
	});

	// --- pencarian & filter ---
	$search.on('keydown', (e) => {
		if (e.which === 13 || e.key === 'Enter') {
			load();
		}
	});
	$main.find('.wzrq-refresh').on('click', load);
	$main.on('click', '.wzrq-more-btn', () => load({ append: true }));

	// Esc menutup popover filter/pemilih kolom/panel tampilan (selain klik-luar)
	$(document).on('keydown.wzrq', (e) => {
		if (e.key === 'Escape') {
			$pop.hide();
			$colsPop.hide();
			$panel.hide();
		}
	});

	const $pop = $main.find('.wzrq-filter-pop');
	$main.find('.wzrq-filter-btn').on('click', function (e) {
		e.stopPropagation();
		wzrq_ensure_meta(() => {
			wzrq_render_filter_rows($main);
			$pop.toggle();
		});
	});
	// JANGAN stopPropagation di $pop — handler ubah/tambah filter terikat
	// delegated dari $main; cukup tutup popover hanya untuk klik di luar.
	$(document).on('click.wzrq', (e) => {
		if (!$(e.target).closest('.wzrq-filter-pop, .wzrq-filter-btn').length) {
			$pop.hide();
		}
		if (!$(e.target).closest('.wzrq-cols-pop, .wzrq-cols-btn').length) {
			$colsPop.hide();
		}
	});

	$main.on('click', '.wzrq-filter-add', () => {
		wzrq_ensure_meta(() => {
			const first_field = Object.keys(WZRQ_FIELD_META)[0];
			WZRQ_FILTERS.push({ field: first_field, operator: WZRQ_FIELD_META[first_field].operators[0], value: '' });
			wzrq_render_filter_rows($main);
		});
	});

	$main.on('click', '.wzrq-filter-clearall', () => {
		WZRQ_FILTERS = [];
		wzrq_render_filter_rows($main);
		wzrq_update_filter_count($main_page);
		load();
	});

	$pop.on('change', '.wzrq-ff', function () {
		wzrq_collect_rows($main);
		const idx = $(this).closest('.wzrq-filter-row').attr('data-idx');
		const meta = WZRQ_FIELD_META[this.value];
		WZRQ_FILTERS[idx].field = this.value;
		WZRQ_FILTERS[idx].operator = meta.operators[0];
		WZRQ_FILTERS[idx].value = '';
		wzrq_render_filter_rows($main);
		apply_soon();
	});

	$pop.on('change input', '.wzrq-fo, .wzrq-fv, .wzrq-fd1, .wzrq-fd2', function () {
		const row = $(this).closest('.wzrq-filter-row');
		const idx = row.attr('data-idx');
		const prev_op = WZRQ_FILTERS[idx].operator;
		WZRQ_FILTERS[idx].operator = row.find('.wzrq-fo').val();
		const $d1 = row.find('.wzrq-fd1');
		if ($d1.length) {
			WZRQ_FILTERS[idx].value = [$d1.val() || '', row.find('.wzrq-fd2').val() || ''];
		} else {
			WZRQ_FILTERS[idx].value = row.find('.wzrq-fv').val() || '';
		}
		// ganti operator pada field Date mengubah bentuk input (between = 2
		// input tanggal) — baris filter perlu dirender ulang
		if (
			WZRQ_FIELD_META[WZRQ_FILTERS[idx].field] &&
			WZRQ_FIELD_META[WZRQ_FILTERS[idx].field].fieldtype === 'Date' &&
			prev_op !== WZRQ_FILTERS[idx].operator
		) {
			wzrq_render_filter_rows($main);
		}
		wzrq_update_filter_count($main_page);
		apply_soon();
	});

	$pop.on('click', '.wzrq-fx', function () {
		WZRQ_FILTERS.splice($(this).closest('.wzrq-filter-row').attr('data-idx'), 1);
		wzrq_render_filter_rows($main);
		wzrq_update_filter_count($main_page);
		load();
	});

	// --- pilih kolom tabel (ala list view ERPNext) ---
	const $colsPop = $main.find('.wzrq-cols-pop');
	function wzrq_build_cols_pop() {
		const visible = wzrq_visible_columns();
		$colsPop.html(
			`<div class="wzrq-cols-title">${__('Choose columns')}</div>` +
				WZRQ_ALL_COLUMNS.map(
					(c) =>
						`<label class="wzrq-cols-item"><input type="checkbox" class="wzrq-col-toggle" value="${c.key}"${visible.includes(c.key) ? ' checked' : ''} /> ${c.label}</label>`
				).join(''),
		);
	}
	$main.on('click', '.wzrq-cols-btn', function (e) {
		e.stopPropagation();
		wzrq_build_cols_pop();
		$colsPop.toggle();
	});
	$colsPop.on('change', '.wzrq-col-toggle', () => {
		const checked = $colsPop
			.find('.wzrq-col-toggle:checked')
			.map(function () {
				return this.value;
			})
			.get();
		wzrq_set_visible_columns(checked);
		// render ulang tanpa fetch — data baris masih ada di scope; tbody
		// dirender polos, jadi `selected` ikut dikosongkan (pola .wzrq-uom)
		selected.clear();
		wzrq_render($main_page, wzrq_rows($main_page));
	});

	// --- panel tampilan (kepadatan) ---
	const $panel = $main.find('.wzrq-tweak-panel');
	$main.find('.wzrq-tweak-btn').on('click', () => $panel.toggle());
	function apply_density(mode) {
		$main.toggleClass('wzrq-compact', mode === 'compact');
		$main.find('.wzrq-den-comfort').toggleClass('btn-primary', mode !== 'compact');
		$main.find('.wzrq-den-compact').toggleClass('btn-primary', mode === 'compact');
		try {
			localStorage.setItem('wzrq_density', mode);
		} catch (e) {
			/* private mode: abaikan */
		}
	}
	$main.find('.wzrq-den-comfort').on('click', () => apply_density('comfort'));
	$main.find('.wzrq-den-compact').on('click', () => apply_density('compact'));
	let density = 'comfort';
	try {
		density = localStorage.getItem('wzrq_density') || 'comfort';
	} catch (e) {
		/* default */
	}
	apply_density(density);

	load();
};

// P2 review W9: muat ulang tiap kali halaman tampil lagi, supaya badge
// "Diminta" tidak basi setelah navigasi pergi-pulang. Tanpa freeze — cukup
// redupkan tabel supaya tidak ada flash konten basi yang terlihat final.
frappe.pages['gudang_request'].on_page_show = function (wrapper) {
	const $scope = $(wrapper);
	if (!$scope.find('.wzrq-search').length) {
		return;
	}
	wzrq_set_loading($scope, true);
	frappe.call({
		method: 'warehouse_app.warehouse_app.gudang_request.requestable_work_orders',
		args: {
			search: $scope.find('.wzrq-search').val() || '',
			filters: JSON.stringify(active_filters()),
		},
		// dua-argumen, bukan .finally(): promise frappe.call (jQuery) tidak
		// menjamin .finally — kelas loading bisa nyangkut selamanya
	}).then(
		(r) => {
			const rows = (r.message && r.message.length && r.message) || [];
			$scope.data('wzrq_last_fetch', rows.length);
			wzrq_render($scope, rows);
			wzrq_set_loading($scope, false);
		},
		() => wzrq_set_loading($scope, false)
	);
};

// ---------------- filter ala list view ERPNext

function active_filters() {
	return WZRQ_FILTERS.filter((f) => {
		if (Array.isArray(f.value)) {
			return f.value.some((x) => String(x || '').trim() !== '');
		}
		return String(f.value || '').trim() !== '';
	});
}

function wzrq_ensure_meta(done) {
	if (WZRQ_FIELD_META) {
		done && done();
		return;
	}
	frappe
		.call({ method: 'warehouse_app.warehouse_app.gudang_request.filter_fields' })
		.then((r) => {
			WZRQ_FIELD_META = r.message || {};
			done && done();
		});
}

function wzrq_render_filter_rows($main) {
	const $rows = $main.find('.wzrq-filter-rows');
	if (!WZRQ_FILTERS.length) {
		$rows.html(`<div class="text-muted wzrq-filter-none">${__('No filters')}</div>`);
		return;
	}
	$rows.html(
		WZRQ_FILTERS.map((f, i) => {
			const meta = WZRQ_FIELD_META[f.field] || { operators: ['like'], fieldtype: 'Data' };
			const field_opts = Object.keys(WZRQ_FIELD_META)
				.map((fname) => `<option value="${wzrq_esc(fname)}"${fname === f.field ? ' selected' : ''}>${wzrq_esc(WZRQ_FIELD_META[fname].label)}</option>`)
				.join('');
			const op_opts = meta.operators
				.map((op) => `<option value="${wzrq_esc(op)}"${op === f.operator ? ' selected' : ''}>${wzrq_esc(wzrq_op_label(op))}</option>`)
				.join('');
			let value_ctl;
			if (meta.fieldtype === 'Date' && f.operator === 'between') {
				const parts = Array.isArray(f.value) ? f.value : String(f.value || '').split(',');
				value_ctl = `<div class="wzrq-fv wzrq-fv-range"><input type="date" class="form-control wzrq-fd1" value="${wzrq_esc(parts[0] || '')}" /><span class="wzrq-fdash">–</span><input type="date" class="form-control wzrq-fd2" value="${wzrq_esc(parts[1] || '')}" /></div>`;
			} else if (meta.fieldtype === 'Date') {
				value_ctl = `<input type="date" class="form-control wzrq-fv" value="${wzrq_esc(f.value)}" />`;
			} else if (meta.fieldtype === 'Select' && meta.options) {
				value_ctl =
					`<select class="form-control wzrq-fv"><option value="">—</option>` +
					meta.options
						.map((o) => `<option value="${wzrq_esc(o)}"${o === f.value ? ' selected' : ''}>${wzrq_esc(o)}</option>`)
						.join('') +
					`</select>`;
			} else if (meta.fieldtype === 'Float') {
				value_ctl = `<input type="number" class="form-control wzrq-fv" step="1" min="0" value="${wzrq_esc(f.value)}" />`;
			} else {
				value_ctl = `<input type="text" class="form-control wzrq-fv" value="${wzrq_esc(f.value)}" placeholder="${wzrq_esc(meta.placeholder || '')}" />`;
			}
			return `
				<div class="wzrq-filter-row" data-idx="${i}">
					<select class="form-control wzrq-ff">${field_opts}</select>
					<select class="form-control wzrq-fo">${op_opts}</select>
					${value_ctl}
					<button class="btn btn-default btn-sm wzrq-fx" title="${__('Remove filter')}">×</button>
				</div>`;
		}).join(''),
	);
}

function wzrq_op_label(op) {
	const map = {
		'=': '=',
		'!=': '≠',
		like: 'like',
		'not like': 'not like',
		between: 'between',
		'>=': '≥',
		'<=': '≤',
		'>': '>',
		'<': '<',
	};
	return map[op] || op;
}

function wzrq_collect_rows($main) {
	const rows = [];
	$main.find('.wzrq-filter-row').each(function () {
		const $d1 = $(this).find('.wzrq-fd1');
		if ($d1.length) {
			// operator between: dua input tanggal dikumpulkan sebagai array
			rows.push({
				field: $(this).find('.wzrq-ff').val(),
				operator: $(this).find('.wzrq-fo').val(),
				value: [$d1.val() || '', $(this).find('.wzrq-fd2').val() || ''],
			});
			return;
		}
		rows.push({
			field: $(this).find('.wzrq-ff').val(),
			operator: $(this).find('.wzrq-fo').val(),
			value: $(this).find('.wzrq-fv').val() || '',
		});
	});
	WZRQ_FILTERS = rows;
}

function wzrq_update_filter_count($scope) {
	const n = active_filters().length;
	$scope.find('.wzrq-filter-count').text(n ? `(${n})` : '');
	$scope.find('.wzrq-filter-btn').toggleClass('wzrq-filter-active', n > 0);
}

// ---------------- helpers render (global: dipakai on_page_load & on_page_show)

function wzrq_rows($scope) {
	return $scope.data('wzrq_rows') || [];
}

// definisi kolom tabel ala list view ERPNext — urutan tetap, show/hide
// via popover "Choose columns" (persist di localStorage)
const WZRQ_ALL_COLUMNS = [
	{
		key: 'batch',
		label: __('Batch'),
		cls: 'wzrq-col-adonan',
		cell: (r) => `<span class="wzrq-adonan">${r.custom_adonan_ke ? wzrq_esc(r.custom_adonan_ke) : '—'}</span>`,
	},
	{ key: 'item', label: __('Item'), cls: 'wzrq-col-item', cell: (r) => wzrq_esc(r.item_name) },
	{ key: 'item_code', label: __('Item Code'), cls: 'wzrq-col-item-code', cell: (r) => wzrq_esc(r.production_item || '') },
	{
		key: 'qty',
		label: __('Qty'),
		cls: 'wzrq-col-qty',
		cell: (r) => {
			// uom terpilih per baris: display -> expected units, selain itu stock
			if (wzrq_is_display_uom(r, WZRQ_QTY_UOM || '')) {
				return `${Number(r.expected_units != null ? r.expected_units : 0).toLocaleString('en-US')} <span class="text-muted">${wzrq_esc(r.display_uom)}</span>`;
			}
			return `${Number(r.produced_qty || 0).toLocaleString('en-US')} <span class="text-muted">${wzrq_esc(r.stock_uom)}</span>`;
		},
	},
	{ key: 'wo', label: __('Work Order'), cls: 'wzrq-col-wo', cell: (r) => wzrq_esc(r.name) },
	{ key: 'warehouse', label: __('Warehouse'), cls: 'wzrq-col-warehouse', cell: (r) => wzrq_esc(r.fg_warehouse || '') },
	{ key: 'created', label: __('Created'), cls: 'wzrq-col-created', cell: (r) => wzrq_esc(r.creation ? frappe.datetime.str_to_user(r.creation) : '') },
	{
		key: 'status',
		label: __('Status'),
		cls: 'wzrq-col-status',
		cell: (r) => {
			// W19: anggota grup box bersama — penanda kecil setelah link MR
			const grp = r.box_plan
				? ` <span class="text-muted wzrq-grp">· ${__('Group ({0} WO)', [r.group_size || 0])}</span>`
				: '';
			if (r.request_active) {
				return `<span class="indicator-pill orange">${__('Requested')} · <a href="/app/material-request/${wzrq_esc(r.custom_handover_material_request)}">${wzrq_esc(r.custom_handover_material_request)}</a>${grp}</span>`;
			}
			if (r.request_shipped) {
				return `<span class="indicator-pill green">${__('Shipped')} · <a href="/app/material-request/${wzrq_esc(r.custom_handover_material_request)}">${wzrq_esc(r.custom_handover_material_request)}</a>${grp}</span>`;
			}
			return `<span class="indicator-pill blue">${wzrq_esc(r.status)}</span>`;
		},
	},
];

function wzrq_visible_columns() {
	if (WZRQ_VISIBLE) {
		return WZRQ_VISIBLE;
	}
	let keys = null;
	try {
		keys = JSON.parse(localStorage.getItem('wzrq_columns') || 'null');
	} catch (e) {
		keys = null;
	}
	if (!Array.isArray(keys) || !keys.length) {
		keys = WZRQ_ALL_COLUMNS.map((c) => c.key);
	}
	WZRQ_VISIBLE = keys.filter((k) => WZRQ_ALL_COLUMNS.some((c) => c.key === k));
	return WZRQ_VISIBLE;
}

function wzrq_set_visible_columns(keys) {
	WZRQ_VISIBLE = keys;
	try {
		localStorage.setItem('wzrq_columns', JSON.stringify(keys));
	} catch (e) {
		/* private mode: abaikan */
	}
}

// layar sempit dan user belum pernah mengatur kolom sendiri
function wzrq_secondary_collapsed() {
	try {
		if (localStorage.getItem('wzrq_columns')) {
			return false;
		}
	} catch (e) {
		/* private mode: anggap tanpa preferensi */
	}
	return window.innerWidth <= 640;
}

function wzrq_store(key, value) {
	try {
		localStorage.setItem(key, value);
	} catch (e) {
		/* private mode: abaikan */
	}
}

function wzrq_load(key) {
	try {
		return localStorage.getItem(key) || '';
	} catch (e) {
		return '';
	}
}

// union uom baris termuat: stock dulu, lalu display — dedup, urutan stabil
function wzrq_uom_options(rows) {
	const opts = [];
	rows.forEach((r) => {
		if (r.stock_uom && !opts.includes(r.stock_uom)) {
			opts.push(r.stock_uom);
		}
	});
	rows.forEach((r) => {
		if (r.display_uom && !opts.includes(r.display_uom)) {
			opts.push(r.display_uom);
		}
	});
	return opts;
}

// baris tampil dalam display UOM hanya bila konversinya valid dan uom
// terpilih = display uom baris itu; selain itu (termasuk factor tak
// valid / uom tak dikenal baris) -> fallback stock
function wzrq_is_display_uom(r, uom) {
	const factor = Number(r.display_conversion_factor);
	return !!(r.display_uom && r.display_uom !== r.stock_uom && isFinite(factor) && factor > 0 && uom === r.display_uom);
}

// segarkan opsi .wzrq-uom dari baris termuat + normalkan pilihan tersimpan
// (tak ada di opsi -> default stock uom). Tanpa baris, opsi terakhir
// dibiarkan. Mengembalikan uom aktif ('' bila belum ada).
function wzrq_sync_uom_select($main, rows) {
	if (WZRQ_QTY_UOM === null) {
		WZRQ_QTY_UOM = wzrq_load('wzrq_qty_uom');
	}
	const $sel = $main.find('.wzrq-uom');
	if (!$sel.length) {
		return WZRQ_QTY_UOM;
	}
	if (rows.length) {
		const opts = wzrq_uom_options(rows);
		if (!WZRQ_QTY_UOM || !opts.includes(WZRQ_QTY_UOM)) {
			WZRQ_QTY_UOM = opts[0];
			wzrq_store('wzrq_qty_uom', WZRQ_QTY_UOM);
		}
		$sel.html(opts.map((o) => `<option value="${wzrq_esc(o)}">${wzrq_esc(o)}</option>`).join(''));
	}
	$sel.val(WZRQ_QTY_UOM);
	return WZRQ_QTY_UOM;
}

function wzrq_set_loading($scope, on) {
	$scope.find('.wzrq-table-wrap').toggleClass('wzrq-loading', !!on);
}

function wzrq_render($scope, rows) {
	$scope.data('wzrq_rows', rows);
	const $main = $scope.find('.layout-main');
	const uom = wzrq_sync_uom_select($main, rows);
	let col_keys = wzrq_visible_columns();
	// layar sempit dan user belum pernah mengatur kolom: kolom sekunder
	// disingkirkan agar tabel tidak mepet — pilihan eksplisit pemilih kolom
	// tetap menang (tersimpan di localStorage, path ini tidak lagi aktif).
	if (wzrq_secondary_collapsed()) {
		col_keys = col_keys.filter((k) => k !== 'item_code' && k !== 'created');
	}
	const cols = col_keys.map((key) => WZRQ_ALL_COLUMNS.find((c) => c.key === key));
	$main.find('.wzrq-table thead tr').html(
		`<th class="wzrq-col-check"><input type="checkbox" class="wzrq-check-all" aria-label="${__('Select all')}" /></th>` +
			cols
				.map((c) => `<th class="${c.cls}">${c.key === 'qty' && uom ? __('Qty ({0})', [wzrq_esc(uom)]) : c.label}</th>`)
				.join('') +
			`<th class="wzrq-col-aksi"><button type="button" class="wzrq-cols-btn" title="${__('Choose columns')}"><svg width="14" height="14" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><line x1="4" y1="21" x2="4" y2="14"/><line x1="4" y1="10" x2="4" y2="3"/><line x1="12" y1="21" x2="12" y2="12"/><line x1="12" y1="8" x2="12" y2="3"/><line x1="20" y1="21" x2="20" y2="16"/><line x1="20" y1="12" x2="20" y2="3"/><line x1="1" y1="14" x2="7" y2="14"/><line x1="9" y1="8" x2="15" y2="8"/><line x1="17" y1="16" x2="23" y2="16"/></svg></button></th>`,
	);
	$main.find('.wzrq-table tbody').html(rows.map((r) => wzrq_row_html(r, cols)).join(''));
	$main.find('.wzrq-empty').toggle(rows.length === 0);
	const $foot = $main.find('.wzrq-foot');
	$foot.toggle(rows.length > 0);
	$main.find('.wzrq-count').text(
		rows.length === 1 ? __('1 Work Order') : __('{0} Work Orders', [rows.length])
	);
	// Load more hanya saat fetch terakhir memenuhi satu halaman penuh (50)
	$main.find('.wzrq-more-btn').toggle(rows.length > 0 && $scope.data('wzrq_last_fetch') >= 50);
	wzrq_update_bulk($scope, new Set());
}

function wzrq_update_bulk($scope, selected) {
	const rows = wzrq_rows($scope);
	const selectable = rows.filter((r) => !r.request_active && !r.request_shipped);
	const sel_rows = selectable.filter((r) => selected.has(r.name));
	const n = sel_rows.length;
	const $main = $scope.find('.layout-main');
	$main.find('.wzrq-bulk-count').text(n ? __('{0} selected', [n]) : '');
	$main.find('.wzrq-bulk-request').prop('disabled', !n);
	// W19: trigger grup — ≥2 baris, satu item yang sama, item terdaftar grup.
	// Dinilai ulang di SETIAP perubahan seleksi (fungsi ini satu-satunya
	// tempat tombol bulk diperbarui).
	const group_rows =
		n >= 2 &&
		sel_rows.every((r) => r.group_item) &&
		new Set(sel_rows.map((r) => r.production_item)).size === 1
			? sel_rows
			: null;
	$scope.data('wzrq_group', group_rows);
	$main.find('.wzrq-bulk-request').text(
		group_rows
			? __('Create Group Request ({0})', [n])
			: n
				? __('Create Request ({0})', [n])
				: __('Create Request'),
	);
	$main.find('.wzrq-bulk-clear').toggle(n > 0);
	$main
		.find('.wzrq-check-all')
		.prop('checked', selectable.length > 0 && n >= selectable.length)
		.prop('indeterminate', n > 0 && n < selectable.length);
}

function wzrq_esc(value) {
	return frappe.utils.escape_html(value == null ? '' : String(value));
}

function wzrq_row_html(r, cols) {
	const active = r.request_active;
	const done = active || r.request_shipped; // requested/shipped: non-selectable
	const mr = r.custom_handover_material_request;
	const aksi = active
		? `<button class="btn btn-xs btn-default wzrq-cancel" data-mr="${wzrq_esc(mr)}"${r.box_plan ? ` data-plan="${wzrq_esc(r.box_plan)}" data-size="${Number(r.group_size || 0)}"` : ''}>${__('Cancel')}</button>`
		: '';
	return `
		<tr class="wzrq-row${done ? ' is-active' : ''}" data-wo="${wzrq_esc(r.name)}">
			<td class="wzrq-col-check"><input type="checkbox" class="wzrq-check"${done ? ' disabled' : ''} aria-label="${wzrq_esc(r.name)}" /></td>
			${cols.map((c) => `<td class="${c.cls}">${c.cell(r)}</td>`).join('')}
			<td class="wzrq-col-aksi">${aksi}</td>
		</tr>`;
}

// ---------------- aksi

// Dialog alokasi Box untuk N WO terpilih: satu baris per WO, prefilled
// jumlah Box 1 mengikuti uom qty terpilih (display -> expected units,
// stock -> produced qty). Server tetap validator kebenaran — atomic.
function bulk_dialog(wos, done) {
	// uom input qty: preferensi tersimpan -> display uom baris pertama
	let dialog_uom = wzrq_load('wzrq_dialog_uom');
	const uom_opts = wzrq_uom_options(wos);
	if (!uom_opts.includes(dialog_uom)) {
		dialog_uom = (wos[0] && (wos[0].display_uom || wos[0].stock_uom)) || '';
	}

	const rows_html = wos
		.map(
			(r) => `
			<tr data-wo="${wzrq_esc(r.name)}" data-factor="${wzrq_esc(r.display_conversion_factor || 1)}" data-item="${wzrq_esc(r.item_name || r.production_item || '')}" data-stock-uom="${wzrq_esc(r.stock_uom || '')}" data-display-uom="${wzrq_esc(r.display_uom || '')}">
				<td class="wzrq-dt-wo">
					<div class="wzrq-dt-title">${__('Batch')} <b>${wzrq_esc(r.custom_adonan_ke || '-')}</b> · ${wzrq_esc(r.item_name)}</div>
					<div class="wzrq-dt-meta text-muted">${wzrq_esc(r.name)} · ${__('yield {0} {1}', [Number(r.produced_qty || 0).toLocaleString('en-US'), wzrq_esc(r.stock_uom)])}${r.display_uom && r.display_uom !== r.stock_uom ? ` · ${Number(r.expected_units != null ? r.expected_units : 0).toLocaleString('en-US')} ${wzrq_esc(r.display_uom)}` : ''}</div>
				</td>
				<td class="wzrq-dt-cell"><input type="number" class="form-control wzrq-kg1" min="0" step="0.01" placeholder="kg" title="${__('Box 1 (kg)')}" /></td>
				<td class="wzrq-dt-cell"><input type="number" class="form-control wzrq-qty1" min="0" step="1" value="${wzrq_is_display_uom(r, dialog_uom) ? Number(r.expected_units != null ? r.expected_units : 0) : Math.round(Number(r.produced_qty || 0))}" title="${__('Box 1 (qty)')}" /></td>
				<td class="wzrq-dt-cell2">
					<button type="button" class="btn btn-link wzrq-addbox2">+ ${__('Box 2')}</button>
					<div class="wzrq-box2-inputs" style="display:none">
						<input type="number" class="form-control wzrq-kg2" min="0" step="0.01" placeholder="kg" title="${__('Box 2 (kg)')}" />
						<input type="number" class="form-control wzrq-qty2" min="0" step="1" value="0" title="${__('Box 2 (qty)')}" />
					</div>
					<button type="button" class="btn btn-link wzrq-addbox3" style="display:none">+ ${__('Box 3')}</button>
					<div class="wzrq-box3-inputs" style="display:none">
						<input type="number" class="form-control wzrq-kg3" min="0" step="0.01" placeholder="kg" title="${__('Box 3 (kg)')}" />
						<input type="number" class="form-control wzrq-qty3" min="0" step="1" value="0" title="${__('Box 3 (qty)')}" />
					</div>
				</td>
			</tr>`
		)
		.join('');

	const d = new frappe.ui.Dialog({
		title: __('Box Allocation ({0} Work Orders)', [wos.length]),
		size: 'large',
	});
	d.$body.html(`
		<p class="text-muted wzrq-dt-hint">
			<span>${__('Box 1 is required. Box 2 and Box 3 are optional: click + Box 2, then + Box 3, to add them.')}</span>
			<span class="wzrq-dt-uom">${__('Qty in')} <select class="form-control wzrq-duom">${uom_opts.map((o) => `<option value="${wzrq_esc(o)}"${o === dialog_uom ? ' selected' : ''}>${wzrq_esc(o)}</option>`).join('')}</select></span>
		</p>
		<table class="wzrq-dtable">
			<thead>
				<tr>
					<th class="wzrq-dt-wo">${__('Work Order')}</th>
					<th>${__('Box 1 · kg')}</th>
					<th>${__('Box 1 · qty')}</th>
					<th>${__('Box 2 / 3 · optional')}</th>
				</tr>
			</thead>
			<tbody>${rows_html}</tbody>
		</table>
	`);

	// Box 2/3 opsional: munculkan pasangan input kg/qty saat diminta.
	// + Box 3 baru terlihat setelah Box 2 dimunculkan (urutan reveal tetap).
	d.$body.on('click', '.wzrq-addbox2', function () {
		const $cell = $(this).closest('.wzrq-dt-cell2');
		$(this).hide();
		$cell.find('.wzrq-addbox3').show();
		$cell.find('.wzrq-box2-inputs').show().find('.wzrq-kg2').trigger('focus');
	});
	d.$body.on('click', '.wzrq-addbox3', function () {
		const $cell = $(this).closest('.wzrq-dt-cell2');
		$(this).hide();
		$cell.find('.wzrq-box3-inputs').show().find('.wzrq-kg3').trigger('focus');
	});

	// ganti uom qty: KONVERSI nilai yang sudah diinput per baris
	// (display = stock/factor, stock = display x factor) — jangan reset kerja user
	d.$body.on('change', '.wzrq-duom', function () {
		const next = this.value;
		d.$body.find('.wzrq-dtable tbody tr').each(function () {
			const $tr = $(this);
			const factor = Number($tr.attr('data-factor'));
			const f = isFinite(factor) && factor > 0 ? factor : 1;
			const to_display = wzrq_tr_is_display($tr, next) && !wzrq_tr_is_display($tr, dialog_uom);
			const to_stock = wzrq_tr_is_display($tr, dialog_uom) && !wzrq_tr_is_display($tr, next);
			if (!to_display && !to_stock) {
				return;
			}
			$tr.find('.wzrq-qty1, .wzrq-qty2, .wzrq-qty3').each(function () {
				const v = parseFloat($(this).val());
				if (!isFinite(v)) {
					return; // input kosong dibiarkan kosong
				}
				$(this).val(String(wzrq_round3(to_display ? v / f : v * f)));
			});
		});
		dialog_uom = next;
		wzrq_store('wzrq_dialog_uom', next);
	});

	d.set_primary_action(__('Create Request'), () => submit_bulk(d, done));
	d.show();
}

// varian wzrq_is_display_uom untuk baris dialog (data di atribut tr)
function wzrq_tr_is_display($tr, uom) {
	const disp = $tr.attr('data-display-uom') || '';
	const stock = $tr.attr('data-stock-uom') || '';
	const factor = Number($tr.attr('data-factor'));
	return !!(disp && disp !== stock && isFinite(factor) && factor > 0 && uom === disp);
}

// bulatkan wajar maks 3 desimal tanpa nol ekor (96.5, bukan 96.500)
function wzrq_round3(x) {
	return Number(x.toFixed(3));
}

async function submit_bulk(d, done) {
	// uom input qty dialog saat submit (mode per baris via atribut tr)
	const uom = d.$body.find('.wzrq-duom').val() || '';
	const payloads = [];
	let invalid = null;
	const not_whole = [];
	d.$body.find('.wzrq-dtable tbody tr').each(function () {
		if (invalid) {
			return;
		}
		const $tr = $(this);
		const kg1 = $tr.find('.wzrq-kg1').val();
		const q1 = $tr.find('.wzrq-qty1').val();
		if (kg1 === '' || kg1 === null || q1 === '' || q1 === null) {
			invalid = $tr.attr('data-wo');
			return;
		}
		// qty input (uom terpilih) -> integer display UOM: kontrak payload API.
		// Kedua jalur wajib bulat: entry langsung di UOM display TIDAK boleh
		// dipotong diam-diam (parseInt lama mengubah 2.5 -> 2 tanpa pesan).
		const factor = Number($tr.attr('data-factor'));
		const f = isFinite(factor) && factor > 0 ? factor : 1;
		const item = $tr.attr('data-item') || $tr.attr('data-wo');
		const item_label = wzrq_esc(item);
		const stock_uom_label = wzrq_esc($tr.attr('data-stock-uom') || '');
		const disp_uom_label = wzrq_esc($tr.attr('data-display-uom') || '');
		const to_display_units = (raw) => {
			if (wzrq_tr_is_display($tr, uom)) {
				const v = parseFloat(raw);
				if (!isFinite(v) || Math.abs(v - Math.round(v)) > 1e-9) {
					not_whole.push(
						__('{0} {1} is not a whole number for {2}.', [
							String(raw),
							wzrq_esc(uom),
							item_label,
						])
					);
					return null;
				}
				return Math.round(v);
			}
			const v = parseFloat(raw);
			const x = v / f;
			const whole = Math.round(x);
			if (Math.abs(x - whole) > 1e-6) {
				not_whole.push(
					__('{0} {1} is not a whole number of {2} for {3} (1 {2} = {4} {1}).', [
						v.toLocaleString('en-US'),
						stock_uom_label,
						disp_uom_label,
						item_label,
						f,
					])
				);
				return null;
			}
			return whole;
		};
		const box_1_qty = to_display_units(q1);
		// Box 2/3 hanya dikirim bila pasangan inputnya dimunculkan
		let box_2 = 0;
		let box_2_qty = 0;
		if ($tr.find('.wzrq-box2-inputs').is(':visible')) {
			const kg2 = $tr.find('.wzrq-kg2').val();
			box_2 = kg2 === '' || kg2 === null ? 0 : parseFloat(kg2);
			const q2 = $tr.find('.wzrq-qty2').val();
			box_2_qty = q2 === '' || q2 === null ? 0 : to_display_units(q2);
		}
		let box_3 = 0;
		let box_3_qty = 0;
		if ($tr.find('.wzrq-box3-inputs').is(':visible')) {
			const kg3 = $tr.find('.wzrq-kg3').val();
			box_3 = kg3 === '' || kg3 === null ? 0 : parseFloat(kg3);
			const q3 = $tr.find('.wzrq-qty3').val();
			box_3_qty = q3 === '' || q3 === null ? 0 : to_display_units(q3);
		}
		if (box_1_qty === null || box_2_qty === null || box_3_qty === null) {
			return; // sudah dicatat di not_whole — abort setelah loop
		}
		payloads.push({
			work_order: $tr.attr('data-wo'),
			box_1: parseFloat(kg1),
			box_1_qty,
			box_2,
			box_2_qty,
			box_3,
			box_3_qty,
		});
	});
	if (invalid) {
		frappe.msgprint({
			title: __('Incomplete data'),
			indicator: 'red',
			message: __('Fill in Box 1 (kg and qty) for every row. Check {0}.', [invalid]),
		});
		return;
	}
	if (not_whole.length) {
		// input Pcs tidak membentuk Pack bulat: nol request terkirim
		frappe.msgprint({
			title: __('Invalid quantity'),
			indicator: 'red',
			message:
				not_whole.length === 1
					? not_whole[0]
					: `<ul>${not_whole.map((m) => `<li>${m}</li>`).join('')}</ul>`,
		});
		return;
	}

	// v16 new desk tidak punya frappe.freeze — matikan tombol saja selama
	// submit supaya tidak dobel-klik (frappe.call error tetap tampil normal).
	const $btn = d.$wrapper.find('.modal .btn-primary');
	$btn.prop('disabled', true);
	const ok_list = [];
	const fail_list = [];
	for (const p of payloads) {
		try {
			const r = await frappe.call({
				method: 'production_app.api.handover.create_request',
				args: p,
			});
			ok_list.push(`${r.message.material_request} (${p.work_order})`);
		} catch (e) {
			fail_list.push({ wo: p.work_order, error: wzrq_err_text(e) });
		}
	}
	d.hide();
	$btn.prop('disabled', false);

	if (fail_list.length) {
		frappe.msgprint({
			title: ok_list.length ? __('Partially created') : __('All failed'),
			indicator: ok_list.length ? 'orange' : 'red',
			message:
				(ok_list.length
					? `<p>${__('Created: {0}', [wzrq_esc(ok_list.join(', '))])}</p>`
					: '') +
				`<p><b>${__('Failed')}:</b></p><ul>` +
				fail_list
					.map((f) => `<li><b>${wzrq_esc(f.wo)}</b> — ${wzrq_esc(f.error)}</li>`)
					.join('') +
				'</ul>',
		});
	} else {
		frappe.show_alert({
			message: __('{0} requests created', [ok_list.length]),
			indicator: 'green',
		});
	}
	done && done();
}

// Pesan error frappe.call bisa berupa Error ber-message, jqXHR dengan
// _server_messages, atau exc (traceback ber-HTML) — rapikan jadi teks polos.
function wzrq_err_text(e) {
	if (!e) {
		return 'Unknown error';
	}
	if (typeof e === 'string') {
		return e;
	}
	if (e.responseJSON) {
		const j = e.responseJSON;
		if (j._server_messages) {
			try {
				const msgs = JSON.parse(j._server_messages);
				const texts = msgs.map((m) => {
					const inner = typeof m === 'string' ? JSON.parse(m) : m;
					return String(inner.message || '').replace(/<[^>]*>/g, '');
				});
				return texts.join(' ');
			} catch (x) {
				/* jatuh ke bawah */
			}
		}
		if (j.exc) {
			return String(j.exc).replace(/<[^>]*>/g, '').trim().split('\n').pop();
		}
		if (j.message) {
			return String(j.message).replace(/<[^>]*>/g, '');
		}
	}
	if (e.message && !/^\[object/.test(e.message)) {
		return String(e.message).replace(/<[^>]*>/g, '');
	}
	return 'HTTP ' + (e.status || '?');
}

function cancel_request(material_request, done) {
	frappe.confirm(__('Cancel handover request {0} that has not been shipped?', [material_request]), () => {
		frappe.call({
			method: 'production_app.api.handover.cancel_request',
			args: { material_request: material_request },
			freeze: true,
			freeze_message: __('Cancelling request...'),
		}).then(() => {
			frappe.show_alert({ message: __('Request cancelled'), indicator: 'orange' });
			done && done();
		});
	});
}

// ---------------- W19: group request (box bersama utk N WO satu item)

// Dialog alokasi box GRUP: K box dibagi bersama N WO — tanpa baris per WO.
// Baris = [Box # · kg · qty]; alokasi harus tepat total unit (live hint,
// tombol utama disabled bila X ≠ Y). Server tetap otoritatif.
function group_dialog(wos, done) {
	// uom input qty: preferensi tersimpan -> display uom baris pertama
	// (pola bulk_dialog); satu item -> satu faktor konversi utk semua baris
	let dialog_uom = wzrq_load('wzrq_dialog_uom');
	const uom_opts = wzrq_uom_options(wos);
	if (!uom_opts.includes(dialog_uom)) {
		dialog_uom = (wos[0] && (wos[0].display_uom || wos[0].stock_uom)) || '';
	}
	const r0 = wos[0] || {};
	const factor = Number(r0.display_conversion_factor || 1);
	const f = isFinite(factor) && factor > 0 ? factor : 1;
	const item_name = r0.item_name || r0.production_item || '';
	const is_disp_uom = (uom) =>
		!!(r0.display_uom && r0.display_uom !== r0.stock_uom && f > 0 && uom === r0.display_uom);
	const total_in = (uom) =>
		wos.reduce(
			(s, r) =>
				s +
				(wzrq_is_display_uom(r, uom)
					? Number(r.expected_units != null ? r.expected_units : 0)
					: Math.round(Number(r.produced_qty || 0))),
			0,
		);

	const d = new frappe.ui.Dialog({
		title: __('Group Box Allocation — {0} · {1} Work Orders', [item_name, wos.length]),
		size: 'large',
	});
	d.$body.html(`
		<p class="text-muted wzrq-dt-hint">
			<span>${__('Shared boxes across {0} Work Orders of {1} — allocate the total exactly.', [wos.length, wzrq_esc(item_name)])} <span class="wzrq-gtotal"></span></span>
			<span class="wzrq-dt-uom">${__('Qty in')} <select class="form-control wzrq-duom">${uom_opts
				.map((o) => `<option value="${wzrq_esc(o)}"${o === dialog_uom ? ' selected' : ''}>${wzrq_esc(o)}</option>`)
				.join('')}</select></span>
		</p>
		<div class="wzrq-grows"></div>
		<button type="button" class="btn btn-link wzrq-gaddbox">+ ${__('Add Box')}</button>
		<p class="text-muted wzrq-galloc"></p>
	`);

	function grow_html(qty) {
		return `<div class="wzrq-grow">
			<span class="wzrq-gnum text-muted"></span>
			<input type="number" class="form-control wzrq-gkg" min="0" step="0.01" placeholder="kg" title="${__('Box kg')}" />
			<input type="number" class="form-control wzrq-gqty" min="0" step="1" value="${qty == null ? '' : qty}" title="${__('Box qty')}" />
			<button type="button" class="btn btn-link wzrq-gx" title="${__('Remove box')}">×</button>
		</div>`;
	}
	function add_grow(qty) {
		d.$body.find('.wzrq-grows').append(grow_html(qty));
		renumber_grows();
		update_galloc();
	}
	// nomor box mengikuti urutan DOM; × hanya saat >1 baris. Hanya label/
	// tombol yang disentuh — nilai input user tidak diotak-atik.
	function renumber_grows() {
		const $rows = d.$body.find('.wzrq-grows .wzrq-grow');
		$rows.each((i, el) => $(el).find('.wzrq-gnum').text(__('Box {0}', [i + 1])));
		$rows.find('.wzrq-gx').toggle($rows.length > 1);
	}

	add_grow(total_in(dialog_uom));

	d.$body.on('click', '.wzrq-gaddbox', () => {
		add_grow('');
		d.$body.find('.wzrq-grows .wzrq-grow:last .wzrq-gkg').trigger('focus');
	});
	d.$body.on('click', '.wzrq-gx', function () {
		$(this).closest('.wzrq-grow').remove();
		renumber_grows();
		update_galloc();
	});

	// ganti uom qty: KONVERSI nilai terinput display<->stock (pola bulk_dialog)
	d.$body.on('change', '.wzrq-duom', function () {
		const next = this.value;
		const to_display = is_disp_uom(next) && !is_disp_uom(dialog_uom);
		const to_stock = is_disp_uom(dialog_uom) && !is_disp_uom(next);
		if (to_display || to_stock) {
			d.$body.find('.wzrq-gqty').each(function () {
				const v = parseFloat($(this).val());
				if (!isFinite(v)) {
					return; // input kosong dibiarkan kosong
				}
				$(this).val(String(wzrq_round3(to_display ? v / f : v * f)));
			});
		}
		dialog_uom = next;
		wzrq_store('wzrq_dialog_uom', next);
		update_galloc();
	});

	// live hint "Allocated X of Y {uom}" + primary disabled bila belum pas
	function update_galloc() {
		if (d.wzrq_in_flight) {
			return; // jangan sentuh state tombol selama submit berjalan
		}
		const uom = d.$body.find('.wzrq-duom').val() || dialog_uom;
		const disp = is_disp_uom(uom);
		const tot = total_in(uom);
		let x = 0;
		let ok = true;
		d.$body.find('.wzrq-grow').each(function () {
			const kg_raw = $(this).find('.wzrq-gkg').val();
			const q_raw = $(this).find('.wzrq-gqty').val();
			const kg = parseFloat(kg_raw);
			const q = parseFloat(q_raw);
			if (kg_raw === '' || q_raw === '' || !isFinite(kg) || kg <= 0 || !isFinite(q) || q <= 0) {
				ok = false;
				return;
			}
			// display mode kirim parseInt — desimal di hint akan berbohong soal total
			if (disp && Math.abs(q - Math.round(q)) > 1e-6) {
				ok = false;
				return;
			}
			x += q;
		});
		d.$body
			.find('.wzrq-gtotal')
			.text(` ${__('Total {0} {1}', [Number(tot).toLocaleString('en-US'), uom])}`);
		d.$body.find('.wzrq-galloc').text(
			__('Allocated {0} of {1} {2}', [Number(x).toLocaleString('en-US'), Number(tot).toLocaleString('en-US'), uom]),
		);
		d.$wrapper.find('.modal .btn-primary').prop('disabled', !(ok && Math.abs(x - tot) < 1e-6));
	}
	d.$body.on('input change', '.wzrq-gkg, .wzrq-gqty', update_galloc);

	d.set_primary_action(__('Create Group Request'), () => submit_group(d, wos, dialog_uom, is_disp_uom, f, r0, done));
	d.show();
	update_galloc();
}

// qty input (uom terpilih) -> integer display UOM persis pola per-WO:
// display = parseInt; stock = konversi + cek Pack bulat (abort sebelum kirim)
async function submit_group(d, wos, dialog_uom, is_disp_uom, f, r0, done) {
	if (d.wzrq_in_flight) {
		return; // satu call dalam satu waktu — dobel-klik / input race
	}
	d.wzrq_in_flight = true;
	try {
		await _submit_group_inner(d, wos, dialog_uom, is_disp_uom, f, r0, done);
	} finally {
		d.wzrq_in_flight = false;
	}
}

async function _submit_group_inner(d, wos, dialog_uom, is_disp_uom, f, r0, done) {
	const uom = d.$body.find('.wzrq-duom').val() || dialog_uom;
	const disp = is_disp_uom(uom);
	const boxes = [];
	const not_whole = [];
	let invalid = false;
	d.$body.find('.wzrq-grow').each(function (i) {
		const kg_raw = $(this).find('.wzrq-gkg').val();
		const q_raw = $(this).find('.wzrq-gqty').val();
		if (kg_raw === '' || kg_raw === null || q_raw === '' || q_raw === null) {
			invalid = true;
			return;
		}
		const stock_uom = r0.stock_uom || '';
		const display_uom = r0.display_uom || '';
		let qty_units;
		if (disp) {
			// kontrak API = integer display UOM: tolak desimal eksplisit,
			// jangan potong diam-diam (parseInt lama mengubah 2.5 -> 2)
			const v = parseFloat(q_raw);
			if (!isFinite(v) || Math.abs(v - Math.round(v)) > 1e-9) {
				not_whole.push(__('Box {0}: {1} {2} is not a whole number.', [i + 1, String(q_raw), uom]));
				return;
			}
			qty_units = Math.round(v);
		} else {
			const v = parseFloat(q_raw);
			const x = v / f;
			const whole = Math.round(x);
			if (Math.abs(x - whole) > 1e-6) {
				not_whole.push(
					__('Box {0}: {1} {2} is not a whole number of {3} (1 {3} = {4} {2})', [
						i + 1,
						v.toLocaleString('en-US'),
						stock_uom,
						display_uom || uom,
						f,
					]),
				);
				return;
			}
			qty_units = whole;
		}
		boxes.push({ kg: parseFloat(kg_raw), qty: qty_units });
	});
	if (invalid) {
		frappe.msgprint({
			title: __('Incomplete data'),
			indicator: 'red',
			message: __('Fill in kg and qty for every box.'),
		});
		return;
	}
	if (not_whole.length) {
		// qty tidak membentuk Pack bulat: nol request terkirim
		frappe.msgprint({
			title: __('Invalid quantity'),
			indicator: 'red',
			message:
				not_whole.length === 1
					? not_whole[0]
					: `<ul>${not_whole.map((m) => `<li>${m}</li>`).join('')}</ul>`,
		});
		return;
	}

	// v16 new desk tidak punya frappe.freeze — matikan tombol saja selama
	// submit supaya tidak dobel-klik.
	const $btn = d.$wrapper.find('.modal .btn-primary');
	$btn.prop('disabled', true);
	try {
		const r = await frappe.call({
			method: 'production_app.api.handover.create_group_request',
			args: {
				work_orders: JSON.stringify(wos.map((w) => w.name)),
				boxes: JSON.stringify(boxes),
			},
		});
		d.hide();
		frappe.msgprint({
			title: __('Group request created'),
			indicator: 'green',
			message: __('Group request created: {0} · {1} Work Orders · {2} boxes', [
				wzrq_esc((r.message && r.message.box_plan) || ''),
				wos.length,
				boxes.length,
			]),
		});
		done && done();
	} catch (e) {
		// server menolak: dialog tetap terbuka, tidak ada state parsial
		frappe.msgprint({ title: __('Failed'), indicator: 'red', message: wzrq_err_text(e) });
	} finally {
		$btn.prop('disabled', false);
	}
}

// batal grup box bersama: satu endpoint utk SEMUA MR anggota
function cancel_group_request(box_plan, size, done) {
	frappe.confirm(__('Cancel the ENTIRE group ({0} Work Orders)? Boxes are shared — cancel all.', [size]), () => {
		frappe.call({
			method: 'production_app.api.handover.cancel_group_request',
			args: { box_plan: box_plan },
			freeze: true,
			freeze_message: __('Cancelling group request...'),
		}).then(() => {
			frappe.show_alert({ message: __('Group request cancelled'), indicator: 'orange' });
			done && done();
		});
	});
}
