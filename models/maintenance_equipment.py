from odoo import models, fields, api


class MaintenanceEquipment(models.Model):
    _inherit = "maintenance.equipment"

    employee_ids = fields.Many2many("hr.employee", string="Empleados")

    quantity_available = fields.Integer(
        string="Cantidad disponible total",
        readonly=True,
        compute="_compute_quantity_available",
    )
    quantity_used = fields.Integer(
        string="Cantidad asignada total", default=0, readonly=True
    )
    quantity_total_equipment = fields.Integer(
        string="Cantidad total de equipos", default=0, readonly=True
    )

    equipment_lines_ids = fields.One2many(
        "equipment.allocations.line",
        "equipment_id",
        string="Movimientos del equipo",
    )
    warehouse_lines_ids = fields.One2many(
        "warehouse.allocations.line", "equipment_id", string="Almacenes del equipo"
    )

    @api.depends("quantity_total_equipment", "quantity_used")
    def _compute_quantity_available(self):
        for rec in self:
            rec.quantity_available = max(
                rec.quantity_total_equipment - rec.quantity_used, 0
            )
