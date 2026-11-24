from odoo import api, fields, models, _
from odoo.exceptions import UserError
from odoo.modules import module as odoo_module


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    elmi_tool_signout_ids = fields.One2many('elmi.tool.signout', 'employee_id', string='Tool Sign-outs')
    elmi_tool_clearance_ok = fields.Boolean(
        string='Tool Clearance OK',
        compute='_compute_elmi_tool_clearance_ok',
    )

    @api.depends('elmi_tool_signout_ids.state', 'elmi_tool_signout_ids.tool_id')
    def _compute_elmi_tool_clearance_ok(self):
        for employee in self:
            employee.elmi_tool_clearance_ok = not employee._elmi_held_descriptions()

    def _elmi_assigned_equipment(self):
        """Equipment assigned through hr_maintenance.employee_id, which auto-installs with hr and maintenance."""
        self.ensure_one()
        equipment = self.env['maintenance.equipment']
        if 'employee_id' not in equipment._fields:
            return equipment.browse()
        return equipment.search([('employee_id', '=', self.id), ('active', '=', True)])

    def _elmi_held_descriptions(self):
        self.ensure_one()
        # HR officers are not garage roles, but departure still has to name every tool they hold.
        employee = self.sudo()
        names = []
        signouts = employee.elmi_tool_signout_ids.filtered(lambda signout: signout.state in ('out', 'overdue'))
        names.extend(signouts.mapped('tool_id.display_name'))
        names.extend(employee._elmi_assigned_equipment().mapped('display_name'))
        unique = []
        for name in names:
            if name and name not in unique:
                unique.append(name)
        return unique

    def _elmi_notify_storekeepers(self):
        payload = [{
            'id': employee.id,
            'name': employee.name,
            'tools': employee._elmi_held_descriptions(),
        } for employee in self]
        if not payload:
            return
        if odoo_module.current_test:
            self.env['hr.employee']._elmi_create_storekeeper_activities(payload)
            return
        registry = self.env.registry
        uid = self.env.uid
        context = dict(self.env.context)
        with registry.cursor() as cursor:
            env = api.Environment(cursor, uid, context)
            env['hr.employee']._elmi_create_storekeeper_activities(payload)
            cursor.commit()

    @api.model
    def _elmi_create_storekeeper_activities(self, payload):
        group = self.env.ref('elmi_fleet_maintenance.group_elmi_storekeeper', raise_if_not_found=False)
        users = group.all_user_ids.filtered(lambda user: user.active and not user.share) if group else self.env['res.users']
        if not users:
            users = self.env.ref('base.user_admin')
        summary = _('Tool clearance')
        for item in payload:
            employee = self.browse(item['id'])
            if not employee.exists():
                continue
            held = ', '.join(item['tools']) if item['tools'] else _('none')
            note = _('Departure started for %(name)s. Tools still held: %(tools)s', name=item['name'], tools=held)
            for user in users:
                existing = self.env['mail.activity'].search([
                    ('res_model', '=', 'hr.employee'),
                    ('res_id', '=', employee.id),
                    ('user_id', '=', user.id),
                    ('summary', '=', summary),
                ], limit=1)
                if existing:
                    continue
                employee.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=summary,
                    note=note,
                )

    def _elmi_guard_tool_clearance(self):
        employees = self.filtered('active')
        if not employees:
            return
        employees.invalidate_recordset(['elmi_tool_clearance_ok'])
        employees._elmi_notify_storekeepers()
        blocked = employees.filtered(lambda employee: not employee.elmi_tool_clearance_ok)
        if not blocked or self.env.user.has_group('elmi_fleet_maintenance.group_elmi_tool_clearance_override'):
            return
        lines = [
            '%s: %s' % (employee.name, ', '.join(employee._elmi_held_descriptions()))
            for employee in blocked
        ]
        raise UserError(_("Departure is blocked until tool clearance is complete:\n%s") % '\n'.join(lines))

    def action_archive(self):
        if not self.env.context.get('elmi_tool_clearance_checked'):
            self._elmi_guard_tool_clearance()
        return super().action_archive()
