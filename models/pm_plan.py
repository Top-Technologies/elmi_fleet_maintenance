from odoo import api, fields, models, _
from odoo.tools.float_utils import float_compare


class ElmiPmPlanLine(models.Model):
    _name = 'elmi.pm.plan.line'
    _description = 'Meter Preventive Maintenance Plan'
    _order = 'vehicle_id, meter_type, interval'

    name = fields.Char(required=True)
    reference = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    vehicle_id = fields.Many2one('fleet.vehicle', required=True, index=True, ondelete='cascade')
    company_id = fields.Many2one(related='vehicle_id.company_id', store=True, index=True)
    meter_type = fields.Selection(
        [
            ('odometer_km', 'Odometer (km)'),
            ('engine_hours', 'Engine Hours'),
        ],
        required=True,
        default='odometer_km',
    )
    interval = fields.Float(required=True)
    warning_lead_pct = fields.Float(string='Warning Lead (%)')
    last_done_meter = fields.Float(string='Last Done Meter')
    next_due = fields.Float(compute='_compute_next_due', store=True)
    checklist = fields.Text()
    active = fields.Boolean(default=True)
    request_ids = fields.One2many('maintenance.request', 'elmi_pm_plan_line_id', string='Requests')

    @api.depends('last_done_meter', 'interval')
    def _compute_next_due(self):
        for line in self:
            line.next_due = (line.last_done_meter or 0.0) + (line.interval or 0.0)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('reference') or vals.get('reference') == _('New'):
                vals['reference'] = self.env['ir.sequence'].next_by_code('elmi.pm.plan.line') or _('New')
        return super().create(vals_list)

    def _elmi_threshold(self):
        self.ensure_one()
        lead = (self.next_due or 0.0) * (self.warning_lead_pct or 0.0) / 100.0
        return (self.next_due or 0.0) - lead

    def _elmi_open_request(self):
        self.ensure_one()
        return self.env['maintenance.request'].search([
            ('elmi_pm_plan_line_id', '=', self.id),
            ('archive', '=', False),
            ('stage_id.done', '=', False),
        ], limit=1)

    def _elmi_trigger_if_due(self, current_value):
        for line in self:
            if not line.active or not line.interval:
                continue
            if float_compare(current_value, line._elmi_threshold(), precision_digits=2) < 0:
                continue
            if line._elmi_open_request():
                continue
            line._elmi_create_request(current_value)

    def _elmi_create_request(self, current_value):
        self.ensure_one()
        equipment = self.vehicle_id._elmi_primary_equipment()
        team = equipment.maintenance_team_id or self.env['maintenance.team'].search([
            '|', ('company_id', '=', False), ('company_id', '=', self.vehicle_id.company_id.id),
        ], limit=1)
        if not team:
            self.vehicle_id.message_post(body=_(
                "Preventive plan %s is due but no maintenance team is available, so no request was created.",
                self.display_name,
            ))
            return self.env['maintenance.request']
        description = self.checklist or ''
        request = self.env['maintenance.request'].create({
            'name': _('PM %(plan)s at %(meter)s', plan=self.name, meter=current_value),
            'equipment_id': equipment.id,
            'maintenance_team_id': team.id,
            'company_id': self.vehicle_id.company_id.id or self.env.company.id,
            'maintenance_type': 'preventive',
            'recurring_maintenance': False,
            'description': '<p>%s</p>' % description if description else False,
            'elmi_pm_plan_line_id': self.id,
            'elmi_pm_due_meter': self.next_due,
        })
        return request

    @api.model
    def _cron_check_meter_plans(self):
        for line in self.search([('active', '=', True)]):
            current = line.vehicle_id._elmi_meter_value(line.meter_type)
            line._elmi_trigger_if_due(current)
