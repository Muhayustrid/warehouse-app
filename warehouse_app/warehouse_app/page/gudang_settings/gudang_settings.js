// W11: halaman Settings gudang serah terima. Form tipis dua field
// (Source/Target warehouse) di atas setting Manufacturing Settings
// milik production_app — lihat gudang_settings.py untuk batasnya.
// W19: section ketiga "Group Request Items" — daftar item grup-request box
// bersama, disimpan di Warehouse App Settings milik app ini. Satu tombol
// Save menyimpan gudang + item sekaligus (satu flow page).

frappe.pages['gudang_settings'].on_page_load = function (wrapper) {
	const page = frappe.ui.make_app_page({
		parent: wrapper,
		title: __('Settings'),
		single_column: true,
	});

	// endpoint get/set_group_items di-gate role di server; section hanya
	// dimuat/fetch user yang punya role (hindari toast PermissionError).
	const GROUP_ROLES = ['System Manager', 'Gudang Barang Jadi'];
	const can_groups = (frappe.user_roles || []).some((r) => GROUP_ROLES.includes(r));

	const $main = $(wrapper).find('.layout-main');
	// .layout-main Desk v16 = flex row: satu root full-width dengan padding
	$main.html(`
		<div class="wgs-root">
			<p class="text-muted wgs-desc">
				${__('Warehouses used when the warehouse team creates handover requests.')}
			</p>
			<div class="wgs-form">
				<div class="wgs-field">
					<label class="wgs-label">${__('Source Warehouse')}</label>
					<select class="form-control wgs-input" id="wgs-source"></select>
					<p class="wgs-help text-muted">${__('Where the goods come from. Leave empty to follow the production lot warehouse automatically.')}</p>
				</div>
				<div class="wgs-field">
					<label class="wgs-label">${__('Target Warehouse')} <span class="text-danger">*</span></label>
					<select class="form-control wgs-input" id="wgs-target"></select>
					<p class="wgs-help text-muted">${__('Where handover requests deliver the goods. Required to create a request.')}</p>
				</div>
				<div class="wgs-section${can_groups ? '' : ' hide'}">
					<label class="wgs-label">${__('Group Request Items')}</label>
					<p class="wgs-help text-muted" style="margin: 0 0 8px;">${__('Items eligible for group requests — several Work Orders of one item with shared boxes.')}</p>
					<div class="wgs-gitems"></div>
					<div class="wgs-gadd">
						<div class="wgs-gadd-ctrl"></div>
						<button class="btn btn-default btn-sm wgs-gadd-btn">${__('Add')}</button>
					</div>
				</div>
				<div class="wgs-actions">
					<button class="btn btn-primary wgs-save">${__('Save')}</button>
				</div>
			</div>
		</div>
	`);

	const $source = $main.find('#wgs-source');
	const $target = $main.find('#wgs-target');
	const $save = $main.find('.wgs-save');
	const $gitems = $main.find('.wgs-gitems');
	let warehouses = [];
	let group_items = []; // salinan kerja lokal; tersimpan saat Save

	// Link control Item native (frappe.ui.form.ControlLink) — pattern paling
	// sederhana yang memberi pencarian item standar Desk tanpa dependensi baru.
	let item_link = null;
	if (can_groups) {
		item_link = frappe.ui.form.make_control({
			parent: $main.find('.wgs-gadd-ctrl'),
			df: {
				fieldname: 'group_item',
				fieldtype: 'Link',
				options: 'Item',
				label: __('Item'),
				placeholder: __('Add an item...'),
			},
			only_input: true,
		});
		item_link.refresh();
	}

	function fill_select($el, value) {
		$el.html(
			`<option value="">—</option>` +
				warehouses
					.map(
						(w) =>
							`<option value="${frappe.utils.escape_html(w)}"${w === value ? ' selected' : ''}>${frappe.utils.escape_html(w)}</option>`,
					)
					.join(''),
		);
	}

	function render_group_items() {
		$gitems.html(
			group_items.length
				? group_items
						.map(
							(it, i) =>
								`<div class="wgs-gitem"><span class="wgs-gitem-name">${frappe.utils.escape_html(it)}</span><button class="wgs-gitem-x" data-i="${i}" title="${__('Remove')}">×</button></div>`,
						)
						.join('')
				: `<div class="text-muted wgs-gempty">${__('No items configured')}</div>`,
		);
	}

	$gitems.on('click', '.wgs-gitem-x', function () {
		group_items.splice(Number($(this).attr('data-i')), 1);
		render_group_items();
	});

	$main.find('.wgs-gadd-btn').on('click', () => {
		const item = (item_link.get_value() || '').trim();
		if (!item) {
			return;
		}
		if (group_items.includes(item)) {
			frappe.show_alert({ message: __('Item already in the list'), indicator: 'orange' });
			return;
		}
		group_items.push(item);
		item_link.set_value('');
		render_group_items();
	});

	async function load_settings() {
		const calls = [
			frappe.call({ method: 'warehouse_app.warehouse_app.gudang_settings.warehouse_options' }),
			frappe.call({ method: 'warehouse_app.warehouse_app.gudang_settings.get_handover_settings' }),
		];
		if (can_groups) {
			calls.push(frappe.call({ method: 'warehouse_app.warehouse_app.gudang_settings.get_group_items' }));
		}
		const [opts, settings, grp] = await Promise.all(calls);
		warehouses = opts.message || [];
		fill_select($source, settings.message.source);
		fill_select($target, settings.message.target);
		if (grp) {
			group_items = (grp.message && grp.message.items) || [];
			render_group_items();
		}
	}

	$save.on('click', async () => {
		$save.prop('disabled', true);
		try {
			const calls = [
				frappe.call({
					method: 'warehouse_app.warehouse_app.gudang_settings.set_handover_warehouses',
					args: { source: $source.val() || '', target: $target.val() || '' },
				}),
			];
			if (can_groups) {
				calls.push(
					frappe.call({
						method: 'warehouse_app.warehouse_app.gudang_settings.set_group_items',
						args: { items: group_items },
					}),
				);
			}
			const [rw, ri] = await Promise.all(calls);
			fill_select($source, rw.message.source);
			fill_select($target, rw.message.target);
			if (ri) {
				group_items = (ri.message && ri.message.items) || [];
				render_group_items();
			}
			frappe.show_alert({ message: __('Settings saved'), indicator: 'green' });
		} catch (e) {
			// error server (role/validasi) sudah tampil sebagai toast frappe
		} finally {
			$save.prop('disabled', false);
		}
	});

	load_settings();
};
