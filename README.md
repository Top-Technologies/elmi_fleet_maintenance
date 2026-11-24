# Elmi Fleet Maintenance

Garage maintenance for Elmi Olindo Contractors PLC on Odoo 19. The addon extends Fleet, Maintenance, Inventory, Purchase and Employees. It does not depend on a logistics app, Studio, or Approvals.

## Install

```bash
odoo -d <db> -i elmi_fleet_maintenance --stop-after-init
```

Upgrade with `-u elmi_fleet_maintenance`.

## Configure

Open **Settings → Fleet Maintenance** (system administrator) and set, per company:

| Setting | Used by |
| --- | --- |
| Done meter | G-FL-28, actual meter or the due value |
| Labor rate | G-FL-38, default on new work orders. Leave 0 until O-FL-11 |
| Outsourced service product | G-FL-30 |
| Cost rule | G-FL-54. Default is pending until O-FL-22 |
| Replacement RFQ | G-FL-54 draft purchase order |
| Garage store, default part source, consumption location | G-FL-32 |
| In-transit location | G-FL-53 |
| Open days, transit days, repeat count, repeat window | G-FL-55. 0 disables that alert until O-FL-23 |

Also set on each vehicle: **Fleet Class** (heavy or light) and **Part Location**. Flag tools with **Is a Tool**.

Assign the groups Mechanic, Garage Storekeeper, Garage Workshop Head, Heavy Fleet Manager, Light Fleet Manager, Auditor, and Tool clearance override. They are separate privileges so one user can hold more than one. Do not combine Auditor with an operational role. Settings administrators can run the buttons; tool-clearance override is not included in Settings and must be granted on purpose.

## Requirement map

| Ref | What | Files |
| --- | --- | --- |
| Foundation | Equipment linked to the vehicle, groups, settings, sequences, menus | `models/maintenance_equipment.py`, `models/fleet_vehicle.py`, `security/elmi_security.xml`, `security/ir.model.access.csv`, `security/ir_rules.xml`, `models/res_company.py`, `models/res_config_settings.py`, `views/config_views.xml`, `views/menus.xml`, `data/ir_sequence_data.xml` |
| G-FL-02 | Dual meters and safe odometer sync | `models/meter_reading.py`, `views/meter_pm_views.xml` |
| G-FL-03 | Asset status, filters, group-by, kanban decoration | `models/fleet_vehicle.py`, `views/fleet_vehicle_views.xml` |
| G-FL-28 | Meter preventive plans, reading trigger, daily cron | `models/pm_plan.py`, `models/maintenance_request.py`, `data/ir_cron.xml` |
| G-FL-24 | Incident tab on corrective requests | `models/fault_site.py`, `models/maintenance_request.py`, `views/maintenance_views.xml` |
| G-FL-30 | In-house / outsourced and Create RFQ | `models/maintenance_request.py`, `models/purchase_order.py` |
| G-FL-32 | Parts issue, approval, internal transfer, return | `models/part_line.py`, `models/stock_transfer.py`, `models/stock_picking.py` |
| G-FL-38 | Cost build-up, vehicle total, pivot and graph | `models/maintenance_request.py`, `views/maintenance_views.xml` |
| G-FL-41 | Tool sign-out, holder, overdue cron | `models/tool_signout.py`, `views/tool_views.xml` |
| G-FL-42 | Departure blocked while tools are held | `models/hr_employee.py`, `models/hr_departure.py`, `views/hr_employee_views.xml` |
| G-FL-53 | Cannibalization workflow and stock moves | `models/cannibalization.py`, `models/stock_lot.py`, `views/cannibalization_views.xml` |
| G-FL-54 | Cost rule, replacement, procurement hook | `models/cannibalization.py` |
| G-FL-55 | Alerts, aging, parts in transit, replacement aging | `models/cannibalization.py`, `views/cannibalization_views.xml`, `views/menus.xml` |

## Differences from the build brief

- `fleet.vehicle.model.vehicle_type` is only `car` or `bike`. Heavy and light approval uses the new field `fleet.vehicle.elmi_fleet_class`.
- A finished maintenance stage is `maintenance.stage.done`. There is no separate closed stage. `maintenance.request.archive` is the native cancel flag and is treated as closed for asset status.
- `hr_maintenance` auto-installs with `hr` and `maintenance` and already stores the assignee on `maintenance.equipment.employee_id` (label Assigned Employee). Clearance uses that field plus open sign-outs. The current tool holder is `elmi_current_holder_id`.
- Departure starts in `hr.employee.action_archive` (that method archives the employee and, for one employee, opens `hr.departure.wizard`). The wizard method `action_register_departure` is the confirmation action. Both call the same clearance guard.
- `fleet.vehicle.odometer` is the maximum of `fleet.vehicle.odometer`, not the latest date. Kilometre readings are copied only when they are not below that maximum, so a meter replacement cannot drag the native odometer backwards.
- `trip_log` is accepted as a meter source key for imports. No logistics model is read.
- New fields on standard models are prefixed `elmi_`. On new `elmi.*` models the brief's names are used (`vehicle_id`, `qty`, `cost_rule`, and so on). The unit on a part line is `uom_id`.
- Cost figures on `maintenance.request` are `elmi_parts_cost`, `elmi_labor_hours`, `elmi_labor_rate`, `elmi_labor_cost`, `elmi_outsourced_cost`, `elmi_other_cost`, and `elmi_total_cost`.
- `purchase_stock` is not a dependency, so a purchase order does not create a receipt by itself. Link the receipt on `elmi.cannibalization.replacement.receipt_picking_id`. When that transfer is done, the replacement closes.
- Parts returns are a reverse internal transfer. The standard return wizard skips moves whose destination usage is inventory, which is the consumption location.
- Numeric settings default to 0 (alerts off, labor rate 0, cost rule pending).
- Aging bands 0–7, 8–30, 31–90 and 90+ are report bands. They are not the alert thresholds.
- Fleet approval uses the donor vehicle's class. If the class is missing, submit is blocked.
- Part source is the line location, then the default part location, then the garage store (O-FL-22). Donor stock is the lot's internal location, then the vehicle part location, then the garage store.
- Book value currently equals product cost until a real book-value source is chosen.
- `elmi_hook_post_cost_transfer` and `_elmi_create_procurement_request` are extension points. Neither posts a journal entry nor creates a procurement document.
- The storekeeper departure activity is committed on a separate cursor so it survives the blocking `UserError`.

## Open client decisions

- **O-FL-11** labor rate. The company field starts at 0.
- **O-FL-17** tire counts. Not in these twelve requirements, so no tire register was added.
- **O-FL-22** cost rule and part-location rule. Cost rule defaults to pending. Book value is a stand-in for product cost. Part location uses the fallback above.
- **O-FL-23** alert limits. Each limit starts at 0, which disables that alert.
