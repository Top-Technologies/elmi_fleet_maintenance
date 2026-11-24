from odoo import api, fields, models, _


class FleetVehicle(models.Model):
    _inherit = 'fleet.vehicle'

    elmi_fleet_class = fields.Selection(
        [
            ('heavy', 'Heavy'),
            ('light', 'Light'),
        ],
        string='Fleet Class',
        default='light',
        tracking=True,
        help='Odoo fleet models are only car or bike. Heavy and light fleet managers approve cannibalization by this class.',
    )
    elmi_stock_location_id = fields.Many2one(
        'stock.location',
        string='Part Location',
        domain="[('usage', '=', 'internal')]",
        tracking=True,
        help='Stock location that holds parts fitted on this asset. Used when a lot has no single internal location.',
    )
    elmi_primary_meter_type = fields.Selection(
        [
            ('odometer_km', 'Odometer (km)'),
            ('engine_hours', 'Engine Hours'),
        ],
        string='Primary Meter',
        default='odometer_km',
        required=True,
        tracking=True,
    )
    elmi_equipment_ids = fields.One2many('maintenance.equipment', 'elmi_vehicle_id', string='Linked Equipment')
    elmi_meter_reading_ids = fields.One2many('elmi.meter.reading', 'vehicle_id', string='Meter Readings')
    elmi_meter_reading_count = fields.Integer(compute='_compute_elmi_meter_reading_count')
    elmi_current_meter = fields.Float(
        string='Current Meter',
        compute='_compute_elmi_current_meter',
        store=True,
    )
    elmi_last_meter_date = fields.Date(
        string='Last Meter Date',
        compute='_compute_elmi_current_meter',
        store=True,
    )
    elmi_asset_status = fields.Selection(
        [
            ('under_maintenance', 'Under Maintenance'),
            ('assigned', 'Assigned'),
            ('standby', 'Standby'),
        ],
        string='Asset Status',
        compute='_compute_elmi_asset_status',
        store=True,
    )
    elmi_pm_plan_line_ids = fields.One2many('elmi.pm.plan.line', 'vehicle_id', string='Meter PM Plans')
    elmi_maintenance_cost_total = fields.Monetary(
        string='Maintenance Cost',
        compute='_compute_elmi_maintenance_cost_total',
        store=True,
        currency_field='currency_id',
    )
    elmi_cannibalization_count = fields.Integer(compute='_compute_elmi_cannibalization_count')

    @api.depends('elmi_meter_reading_ids')
    def _compute_elmi_meter_reading_count(self):
        grouped = self.env['elmi.meter.reading']._read_group(
            [('vehicle_id', 'in', self.ids)],
            ['vehicle_id'],
            ['__count'],
        )
        counts = {vehicle.id: count for vehicle, count in grouped}
        for vehicle in self:
            vehicle.elmi_meter_reading_count = counts.get(vehicle.id, 0)

    @api.depends(
        'elmi_primary_meter_type',
        'elmi_meter_reading_ids.meter_type',
        'elmi_meter_reading_ids.value',
        'elmi_meter_reading_ids.date',
    )
    def _compute_elmi_current_meter(self):
        for vehicle in self:
            latest = vehicle._elmi_latest_reading(vehicle.elmi_primary_meter_type)
            vehicle.elmi_current_meter = latest.value if latest else 0.0
            vehicle.elmi_last_meter_date = latest.date if latest else False

    @api.depends(
        'driver_id',
        'log_drivers.date_end',
        'elmi_equipment_ids.maintenance_ids.stage_id',
        'elmi_equipment_ids.maintenance_ids.stage_id.done',
        'elmi_equipment_ids.maintenance_ids.archive',
    )
    def _compute_elmi_asset_status(self):
        """Done stages are maintenance.stage.done. Archive is the native cancel flag, treated as closed."""
        for vehicle in self:
            requests = vehicle.elmi_equipment_ids.maintenance_ids
            open_requests = requests.filtered(lambda request: not request.archive and not request.stage_id.done)
            active_assignment = bool(vehicle.driver_id) or bool(vehicle.log_drivers.filtered(lambda log: not log.date_end))
            if open_requests:
                vehicle.elmi_asset_status = 'under_maintenance'
            elif active_assignment:
                vehicle.elmi_asset_status = 'assigned'
            else:
                vehicle.elmi_asset_status = 'standby'

    @api.depends('elmi_equipment_ids.maintenance_ids.elmi_total_cost')
    def _compute_elmi_maintenance_cost_total(self):
        for vehicle in self:
            vehicle.elmi_maintenance_cost_total = sum(vehicle.elmi_equipment_ids.maintenance_ids.mapped('elmi_total_cost'))

    def _compute_elmi_cannibalization_count(self):
        cannibalization = self.env['elmi.cannibalization']
        for vehicle in self:
            vehicle.elmi_cannibalization_count = cannibalization.search_count([
                '|',
                ('donor_vehicle_id', '=', vehicle.id),
                ('recipient_vehicle_id', '=', vehicle.id),
            ])

    def _elmi_latest_reading(self, meter_type):
        self.ensure_one()
        readings = self.elmi_meter_reading_ids.filtered(lambda reading: reading.meter_type == meter_type)
        if not readings:
            return self.env['elmi.meter.reading']
        return readings.sorted(key=lambda reading: (reading.date, reading.id))[-1]

    def _elmi_meter_value(self, meter_type):
        self.ensure_one()
        latest = self._elmi_latest_reading(meter_type)
        return latest.value if latest else 0.0

    def _elmi_primary_equipment(self):
        self.ensure_one()
        equipment = self.elmi_equipment_ids.filtered(lambda item: not item.elmi_is_tool)
        return equipment[:1]

    def action_elmi_open_meter_readings(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Meter Readings'),
            'res_model': 'elmi.meter.reading',
            'view_mode': 'list,form',
            'domain': [('vehicle_id', '=', self.id)],
            'context': {
                'default_vehicle_id': self.id,
                'default_meter_type': self.elmi_primary_meter_type,
            },
        }

    def action_elmi_open_maintenance_cost(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Maintenance Cost'),
            'res_model': 'maintenance.request',
            'view_mode': 'pivot,graph,list,form',
            'domain': [('equipment_id', 'in', self.elmi_equipment_ids.ids)],
        }

    def action_elmi_open_cannibalization(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Cannibalization'),
            'res_model': 'elmi.cannibalization',
            'view_mode': 'list,kanban,form,pivot,graph',
            'domain': ['|', ('donor_vehicle_id', '=', self.id), ('recipient_vehicle_id', '=', self.id)],
            'context': {'default_donor_vehicle_id': self.id},
        }
