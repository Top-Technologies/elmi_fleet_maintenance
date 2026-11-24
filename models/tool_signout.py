from odoo import api, fields, models, _
from odoo.exceptions import UserError, ValidationError


CONDITION_SELECTION = [
    ('good', 'Good'),
    ('fair', 'Fair'),
    ('damaged', 'Damaged'),
]


class ElmiToolSignout(models.Model):
    _name = 'elmi.tool.signout'
    _description = 'Tool Daily Sign-out'
    _inherit = ['mail.thread', 'mail.activity.mixin', 'elmi.security.mixin']
    _order = 'date_out desc, id desc'

    name = fields.Char(readonly=True, copy=False, default=lambda self: _('New'))
    tool_id = fields.Many2one(
        'maintenance.equipment',
        required=True,
        index=True,
        domain="[('elmi_is_tool', '=', True)]",
        tracking=True,
    )
    employee_id = fields.Many2one('hr.employee', required=True, tracking=True)
    company_id = fields.Many2one('res.company', required=True, default=lambda self: self.env.company, index=True)
    date_out = fields.Date(required=True, default=fields.Date.context_today, tracking=True)
    expected_return = fields.Date(required=True, tracking=True)
    date_returned = fields.Date(tracking=True)
    condition_out = fields.Selection(CONDITION_SELECTION, required=True, default='good', tracking=True)
    condition_in = fields.Selection(CONDITION_SELECTION, tracking=True)
    state = fields.Selection(
        [
            ('out', 'Out'),
            ('returned', 'Returned'),
            ('overdue', 'Overdue'),
        ],
        default='out',
        required=True,
        tracking=True,
    )
    storekeeper_id = fields.Many2one('res.users', default=lambda self: self.env.user, tracking=True)

    @api.model_create_multi
    def create(self, vals_list):
        for vals in vals_list:
            if not vals.get('name') or vals.get('name') == _('New'):
                vals['name'] = self.env['ir.sequence'].next_by_code('elmi.tool.signout') or _('New')
        return super().create(vals_list)

    @api.constrains('tool_id', 'state')
    def _check_tool_signout(self):
        for signout in self:
            if signout.tool_id and not signout.tool_id.elmi_is_tool:
                raise ValidationError(_("Only equipment flagged as a tool can be signed out."))
            if signout.state in ('out', 'overdue'):
                duplicate = self.search([
                    ('id', '!=', signout.id),
                    ('tool_id', '=', signout.tool_id.id),
                    ('state', 'in', ('out', 'overdue')),
                ], limit=1)
                if duplicate:
                    raise ValidationError(_(
                        "%s already has an open sign-out (%s).",
                        signout.tool_id.display_name,
                        duplicate.name,
                    ))

    def action_return(self):
        for signout in self:
            if signout.state == 'returned':
                raise UserError(_("This sign-out is already returned."))
            signout.write({
                'state': 'returned',
                'date_returned': fields.Date.context_today(self),
                'condition_in': signout.condition_in or signout.condition_out,
            })
        return True

    @api.model
    def _cron_mark_overdue(self):
        today = fields.Date.context_today(self)
        overdue = self.search([
            ('state', '=', 'out'),
            ('expected_return', '<', today),
        ])
        overdue.write({'state': 'overdue'})
        overdue._elmi_schedule_group_activity(
            'elmi_fleet_maintenance.group_elmi_storekeeper',
            _('Overdue tool'),
            _('This tool is past its expected return. Ask the holder to bring it back.'),
        )
