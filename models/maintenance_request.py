from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError
from odoo.fields import Command


class MaintenanceRequest(models.Model):
    _name = 'maintenance.request'
    _inherit = ['maintenance.request', 'elmi.security.mixin']

    elmi_vehicle_id = fields.Many2one(
        related='equipment_id.elmi_vehicle_id',
        store=True,
        index=True,
        string='Asset',
    )
    elmi_pm_plan_line_id = fields.Many2one('elmi.pm.plan.line', string='Meter PM Plan', index=True, copy=False)
    elmi_pm_due_meter = fields.Float(string='PM Due Meter', copy=False)
    elmi_fault_category_id = fields.Many2one('elmi.fault.category', string='Fault Category', tracking=True)
    elmi_incident_datetime = fields.Datetime(string='Incident Time', tracking=True)
    elmi_site_id = fields.Many2one('elmi.site', string='Site', tracking=True)
    elmi_reported_by_id = fields.Many2one(
        'res.users',
        string='Reported By',
        default=lambda self: self.env.user,
        tracking=True,
    )
    elmi_downtime_start = fields.Datetime(string='Downtime Start', tracking=True)
    elmi_downtime_end = fields.Datetime(string='Downtime End', tracking=True)
    elmi_downtime_hours = fields.Float(string='Downtime Hours', compute='_compute_elmi_downtime_hours', store=True)
    elmi_photo_ids = fields.Many2many(
        'ir.attachment',
        'elmi_request_photo_rel',
        'request_id',
        'attachment_id',
        string='Photos',
    )
    elmi_execution_type = fields.Selection(
        [
            ('in_house', 'In House'),
            ('outsourced', 'Outsourced'),
        ],
        string='Execution',
        default='in_house',
        tracking=True,
    )
    elmi_vendor_id = fields.Many2one('res.partner', string='Vendor', tracking=True)
    elmi_purchase_order_id = fields.Many2one('purchase.order', string='Purchase Order', copy=False, tracking=True)
    elmi_purchase_count = fields.Integer(compute='_compute_elmi_purchase_count')
    elmi_part_line_ids = fields.One2many('elmi.maintenance.part.line', 'request_id', string='Parts')
    currency_id = fields.Many2one(related='company_id.currency_id')
    elmi_parts_cost = fields.Monetary(string='Parts Cost', compute='_compute_elmi_costs', store=True, currency_field='currency_id')
    elmi_labor_hours = fields.Float(string='Labor Hours')
    elmi_labor_rate = fields.Monetary(
        string='Labor Rate',
        currency_field='currency_id',
        default=lambda self: self.env.company.elmi_labor_rate,
    )
    elmi_labor_cost = fields.Monetary(string='Labor Cost', compute='_compute_elmi_costs', store=True, currency_field='currency_id')
    elmi_outsourced_cost = fields.Monetary(string='Outsourced Cost', compute='_compute_elmi_costs', store=True, currency_field='currency_id')
    elmi_other_cost = fields.Monetary(string='Other Cost', currency_field='currency_id')
    elmi_total_cost = fields.Monetary(string='Total Cost', compute='_compute_elmi_costs', store=True, currency_field='currency_id')

    @api.depends('elmi_downtime_start', 'elmi_downtime_end')
    def _compute_elmi_downtime_hours(self):
        for request in self:
            if request.elmi_downtime_start and request.elmi_downtime_end:
                request.elmi_downtime_hours = (request.elmi_downtime_end - request.elmi_downtime_start).total_seconds() / 3600.0
            else:
                request.elmi_downtime_hours = 0.0

    @api.depends('elmi_purchase_order_id')
    def _compute_elmi_purchase_count(self):
        for request in self:
            request.elmi_purchase_count = 1 if request.elmi_purchase_order_id else 0

    @api.depends(
        'elmi_part_line_ids.cost',
        'elmi_part_line_ids.state',
        'elmi_labor_hours',
        'elmi_labor_rate',
        'elmi_purchase_order_id.amount_untaxed',
        'elmi_purchase_order_id.state',
        'elmi_other_cost',
    )
    def _compute_elmi_costs(self):
        for request in self:
            parts = sum(request.elmi_part_line_ids.filtered(lambda line: line.state == 'issued').mapped('cost'))
            labor = (request.elmi_labor_hours or 0.0) * (request.elmi_labor_rate or 0.0)
            purchase = request.elmi_purchase_order_id
            outsourced = purchase.amount_untaxed if purchase and purchase.state != 'cancel' else 0.0
            other = request.elmi_other_cost or 0.0
            request.elmi_parts_cost = parts
            request.elmi_labor_cost = labor
            request.elmi_outsourced_cost = outsourced
            request.elmi_total_cost = parts + labor + outsourced + other

    @api.constrains('elmi_downtime_start', 'elmi_downtime_end')
    def _check_elmi_downtime(self):
        for request in self:
            if request.elmi_downtime_start and request.elmi_downtime_end and request.elmi_downtime_end < request.elmi_downtime_start:
                raise ValidationError(_("Downtime end must be on or after downtime start."))

    @api.constrains('elmi_execution_type', 'elmi_vendor_id')
    def _check_elmi_vendor(self):
        for request in self:
            if request.elmi_execution_type == 'outsourced' and not request.elmi_vendor_id:
                raise ValidationError(_("Select a vendor when execution is outsourced."))

    def write(self, vals):
        becoming_done = self.browse()
        if vals.get('stage_id'):
            stage = self.env['maintenance.stage'].browse(vals['stage_id'])
            if stage.done:
                becoming_done = self.filtered(lambda request: not request.stage_id.done and request.elmi_pm_plan_line_id)
        result = super().write(vals)
        if becoming_done:
            becoming_done._elmi_update_pm_last_done()
        return result

    def _elmi_update_pm_last_done(self):
        for request in self:
            plan = request.elmi_pm_plan_line_id
            if not plan:
                continue
            policy = request.company_id.elmi_pm_done_meter_policy or 'actual'
            vehicle = request.elmi_vehicle_id or plan.vehicle_id
            if policy == 'due':
                meter = request.elmi_pm_due_meter or plan.next_due
            else:
                meter = vehicle._elmi_meter_value(plan.meter_type) if vehicle else (request.elmi_pm_due_meter or plan.next_due)
            plan.last_done_meter = meter
            if vehicle:
                plan._elmi_trigger_if_due(vehicle._elmi_meter_value(plan.meter_type))

    def action_elmi_create_rfq(self):
        self.ensure_one()
        if self.elmi_execution_type != 'outsourced':
            raise UserError(_("Set execution to Outsourced before creating an RFQ."))
        if not self.elmi_vendor_id:
            raise UserError(_("An outsourced request needs a vendor before an RFQ can be created."))
        if self.elmi_purchase_order_id:
            raise UserError(_("An RFQ is already linked to this request."))
        service = self.company_id.elmi_service_product_id
        if not service:
            raise UserError(_("Set the outsourced service product in Fleet Maintenance settings."))
        commands = []
        for part in self.elmi_part_line_ids.filtered(lambda line: line.state != 'returned'):
            commands.append(Command.create(self._elmi_purchase_line_vals(part.product_id, part.qty, part.uom_id)))
        commands.append(Command.create(self._elmi_purchase_line_vals(service, 1.0, service.uom_id)))
        purchase = self.env['purchase.order'].create({
            'partner_id': self.elmi_vendor_id.id,
            'origin': self.name,
            'company_id': self.company_id.id,
            'elmi_maintenance_request_id': self.id,
            'elmi_vehicle_id': self.elmi_vehicle_id.id,
            'order_line': commands,
        })
        for line in purchase.order_line.filtered(lambda item: not item.price_unit):
            line.price_unit = line.product_id.standard_price
        self.elmi_purchase_order_id = purchase.id
        return self.action_elmi_view_purchase_order()

    def _elmi_purchase_line_vals(self, product, qty, uom):
        return {
            'product_id': product.id,
            'product_qty': qty,
            'product_uom_id': uom.id,
            'price_unit': product.standard_price,
            'date_planned': fields.Datetime.now(),
            'name': product.display_name,
        }

    def _elmi_schedule_part_approval(self):
        self._elmi_schedule_group_activity(
            'elmi_fleet_maintenance.group_elmi_workshop_head',
            _('Approve parts'),
            _('Parts were submitted for this work order.'),
        )

    def action_elmi_view_purchase_order(self):
        self.ensure_one()
        return {
            'type': 'ir.actions.act_window',
            'name': _('Purchase Order'),
            'res_model': 'purchase.order',
            'view_mode': 'form',
            'res_id': self.elmi_purchase_order_id.id,
        }
