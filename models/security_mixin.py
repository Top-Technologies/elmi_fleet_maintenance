from odoo import _, models
from odoo.exceptions import AccessError


class ElmiSecurityMixin(models.AbstractModel):
    _name = 'elmi.security.mixin'
    _description = 'Shared group checks and group activities'

    def _elmi_user_has(self, xmlids):
        user = self.env.user
        return any(user.has_group(xmlid) for xmlid in xmlids)

    def _elmi_check_groups(self, xmlids, message):
        allowed = list(xmlids) + ['base.group_system']
        if self._elmi_user_has(allowed):
            return
        raise AccessError(message)

    def _elmi_schedule_group_activity(self, group_xmlid, summary, note):
        """Create one to-do per user in the group, skipping open duplicates."""
        group = self.env.ref(group_xmlid, raise_if_not_found=False)
        users = group.all_user_ids.filtered(lambda user: user.active and not user.share) if group else self.env['res.users']
        if not users:
            users = self.env.ref('base.user_admin')
        for record in self:
            for user in users:
                duplicate = record.activity_ids.filtered(
                    lambda activity: activity.user_id == user and activity.summary == summary
                )
                if duplicate:
                    continue
                record.activity_schedule(
                    'mail.mail_activity_data_todo',
                    user_id=user.id,
                    summary=summary,
                    note=note,
                )
