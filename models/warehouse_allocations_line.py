from odoo import models, fields, api, exceptions


class WarehouseAllocationsLine(models.Model):
    _name = "warehouse.allocations.line"
    _description = "Almacenes de asignación de equipos"
    _rec_name = "display_name"
    _order = "id DESC"

    display_name = fields.Char(string="Nombre", compute="_compute_display_name")
    warehouse_id = fields.Many2one("stock.warehouse", string="Almacén")
    equipment_id = fields.Many2one("maintenance.equipment", string="Equipo")
    employee_ids = fields.Many2many(
        "hr.employee",
        string="Empleados",
        compute="_compute_assigned_employees",
        store=True,
    )

    quantity_used = fields.Integer(
        string="Cantidad usada", compute="_compute_quantities", store=True
    )
    quantity_available = fields.Integer(
        string="Cantidad disponible", compute="_compute_quantities", store=True
    )
    quantity_total = fields.Integer(
        string="Cantidad total", compute="_compute_quantities", store=True
    )

    @api.depends("warehouse_id", "equipment_id")
    def _compute_display_name(self):
        for rec in self:
            rec.display_name = f"{rec.id} / {rec.warehouse_id.name if rec.warehouse_id else 'NA'} / {rec.equipment_id.name if rec.equipment_id else 'NA'}"

    @api.depends(
        "equipment_id",
        "warehouse_id",
        "equipment_id.equipment_lines_ids.move_type",
        "equipment_id.equipment_lines_ids.quantity",
        "equipment_id.equipment_lines_ids.is_applied",
        "equipment_id.equipment_lines_ids.warehouse_origin_id",
        "equipment_id.equipment_lines_ids.warehouse_dest_id",
    )
    def _compute_quantities(self):
        Allocation = self.env["equipment.allocations.line"]

        for rec in self:
            domain = [
                ("equipment_id", "=", rec.equipment_id.id),
                ("is_applied", "=", True),
                "|",
                ("warehouse_origin_id", "=", rec.warehouse_id.id),
                ("warehouse_dest_id", "=", rec.warehouse_id.id),
            ]

            grouped = Allocation.read_group(
                domain, ["move_type", "quantity:sum"], ["move_type"]
            )

            total_in = total_out = assigned = returned = 0

            for row in grouped:
                qty = row.get("quantity") or 0
                move_type = row.get("move_type")

                if move_type == "income":
                    total_in = qty
                elif move_type == "output":
                    total_out = qty
                elif move_type == "assigned":
                    assigned = qty
                elif move_type == "return":
                    returned = qty

            internal_in = Allocation.read_group(
                [
                    ("equipment_id", "=", rec.equipment_id.id),
                    ("move_type", "=", "internal"),
                    ("warehouse_dest_id", "=", rec.warehouse_id.id),
                    ("is_applied", "=", True),
                ],
                ["quantity:sum"],
                [],
            )

            internal_out = Allocation.read_group(
                [
                    ("equipment_id", "=", rec.equipment_id.id),
                    ("move_type", "=", "internal"),
                    ("warehouse_origin_id", "=", rec.warehouse_id.id),
                    ("is_applied", "=", True),
                ],
                ["quantity:sum"],
                [],
            )

            internal_in = internal_in[0]["quantity"] if internal_in else 0
            internal_out = internal_out[0]["quantity"] if internal_out else 0

            rec.quantity_total = total_in - total_out + internal_in - internal_out
            rec.quantity_used = assigned - returned
            rec.quantity_available = rec.quantity_total - rec.quantity_used

    @api.depends(
        "equipment_id",
        "warehouse_id",
        "equipment_id.equipment_lines_ids.move_type",
        "equipment_id.equipment_lines_ids.quantity",
        "equipment_id.equipment_lines_ids.is_applied",
        "equipment_id.equipment_lines_ids.warehouse_origin_id",
        "equipment_id.equipment_lines_ids.warehouse_dest_id",
        "equipment_id.equipment_lines_ids.employee_id",
    )
    def _compute_assigned_employees(self):
        Allocation = self.env["equipment.allocations.line"]

        for rec in self:
            assignment_balance = {}

            domain = [
                ("equipment_id", "=", rec.equipment_id.id),
                ("is_applied", "=", True),
                ("move_type", "in", ["assigned", "return"]),
                "|",
                ("warehouse_origin_id", "=", rec.warehouse_id.id),
                ("warehouse_dest_id", "=", rec.warehouse_id.id),
            ]

            grouped = Allocation.read_group(
                domain,
                ["employee_id", "move_type", "quantity:sum"],
                ["employee_id", "move_type"],
                lazy=False,
            )

            for row in grouped:
                emp = row.get("employee_id")
                if not emp:
                    continue

                emp_id = emp[0]
                qty_sum = row.get("quantity") or 0

                assignment_balance.setdefault(emp_id, 0)
                if row.get("move_type") == "assigned":
                    assignment_balance[emp_id] += qty_sum
                elif row.get("move_type") == "return":
                    assignment_balance[emp_id] -= qty_sum

            positive_ids = [eid for eid, val in assignment_balance.items() if val > 0]
            rec.employee_ids = [(6, 0, positive_ids)]

    @api.constrains("quantity_total", "quantity_used")
    def _check_quantities(self):
        for rec in self:
            if rec.quantity_total < 0:
                raise exceptions.ValidationError(
                    "La cantidad total en el almacén no puede ser negativa."
                )
            if rec.quantity_used < 0:
                raise exceptions.ValidationError(
                    "La cantidad usada no puede ser negativa."
                )
            if rec.quantity_available < 0:
                raise exceptions.ValidationError(
                    "La cantidad disponible no puede ser negativa."
                )
