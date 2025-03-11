import sys
import logging
import configparser
import math
from PyQt6 import QtWidgets, QtCore
from matplotlib.backends.backend_qt5agg import FigureCanvasQTAgg as FigureCanvas
from matplotlib.figure import Figure
import matplotlib.pyplot as plt
import pymysql
from texti import Ui_Form  # Ваш модуль с описанием интерфейса

logging.basicConfig(level=logging.DEBUG)

class DatabaseManager:
    def __init__(self):
        self.config = configparser.ConfigParser()
        self.config.read('config.ini')
        self.connection = None

    def __enter__(self):
        self.connect()
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.disconnect()

    def connect(self):
        try:
            self.connection = pymysql.connect(
                host=self.config.get('Database', 'host'),
                user=self.config.get('Database', 'user'),
                password=self.config.get('Database', 'password'),
                database=self.config.get('Database', 'database'),
                cursorclass=pymysql.cursors.DictCursor
            )
        except Exception as e:
            logging.error(f"Connection error: {str(e)}")
            raise

    def disconnect(self):
        if self.connection:
            self.connection.close()

    def execute_query(self, query, params=None):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params or ())
                if query.strip().upper().startswith('SELECT'):
                    result = cursor.fetchall()
                    logging.debug(f"Query SELECT returned: {result}")
                    return result
                self.connection.commit()
                return cursor.rowcount
        except Exception as e:
            self.connection.rollback()
            logging.error(f"Query error: {str(e)}")
            raise

    def execute_insert(self, query, params=None):
        try:
            with self.connection.cursor() as cursor:
                cursor.execute(query, params or ())
                self.connection.commit()
                last_id = cursor.lastrowid
                logging.debug(f"Insert returned lastrowid: {last_id}")
                return last_id
        except Exception as e:
            self.connection.rollback()
            logging.error(f"Insert error: {str(e)}")
            raise

class CuttingMapsContainer(QtWidgets.QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self.layout = QtWidgets.QHBoxLayout(self)
        self.layout.setContentsMargins(10, 10, 10, 10)
        self.layout.setSpacing(20)

        self.scroll_area = QtWidgets.QScrollArea()
        self.scroll_area.setWidgetResizable(True)
        self.scroll_content = QtWidgets.QWidget()
        self.scroll_layout = QtWidgets.QHBoxLayout(self.scroll_content)
        self.scroll_layout.setAlignment(QtCore.Qt.AlignmentFlag.AlignLeft)
        self.scroll_area.setWidget(self.scroll_content)

        self.layout.addWidget(self.scroll_area)
        self.setLayout(self.layout)

    def clear_maps(self):
        while self.scroll_layout.count():
            item = self.scroll_layout.takeAt(0)
            widget = item.widget()
            if widget:
                widget.deleteLater()

    def add_cutting_map(self, canvas):
        container = QtWidgets.QWidget()
        container.setFixedSize(600, 400)
        layout = QtWidgets.QVBoxLayout(container)
        layout.addWidget(canvas)
        self.scroll_layout.addWidget(container)

class SupplyRequestDialog(QtWidgets.QDialog):
    def __init__(self, material_name, shortage, parent=None):
        super().__init__(parent)
        self.setWindowTitle(f"Заявка на материалы: {material_name}")
        self.shortage = shortage
        layout = QtWidgets.QFormLayout(self)
        self.length_edit = QtWidgets.QLineEdit(self)
        self.width_edit = QtWidgets.QLineEdit(self)
        self.length_edit.setPlaceholderText("Введите длину")
        self.width_edit.setPlaceholderText("Введите ширину")
        layout.addRow("Длина:", self.length_edit)
        layout.addRow("Ширина:", self.width_edit)
        self.buttonBox = QtWidgets.QDialogButtonBox(
            QtWidgets.QDialogButtonBox.StandardButton.Ok | QtWidgets.QDialogButtonBox.StandardButton.Cancel
        )
        layout.addWidget(self.buttonBox)
        self.buttonBox.accepted.connect(self.accept)
        self.buttonBox.rejected.connect(self.reject)

    def get_values(self):
        try:
            length = float(self.length_edit.text())
            width = float(self.width_edit.text())
        except ValueError:
            length, width = 0, 0
        return length, width

class Main(QtWidgets.QWidget, Ui_Form):
    def __init__(self, parent=None):
        super(Main, self).__init__(parent)
        self.setupUi(self)
        self.db_manager = DatabaseManager()
        self.current_order = None

        # Словари для хранения недостающих материалов
        self.fabric_shortage = {}
        self.hardware_shortage = {}
        self.shortage_data = {}

        # Инициализируем область для отображения карт раскроя (только для ткани)
        self.scrollAreaWidgetContents_2.setLayout(QtWidgets.QVBoxLayout())
        self.cutting_maps_container = CuttingMapsContainer()
        self.scrollAreaWidgetContents_2.layout().addWidget(self.cutting_maps_container)

        self.init_ui()
        self.load_orders()

    def init_ui(self):
        self.pushButton_calculate_rascr.clicked.connect(self.calculate_cutting)
        self.pushButton_back.clicked.connect(self.show_order_page)
        # Кнопка для расчёта обрезков
        self.pushButton_calculate_scraps.clicked.connect(self.calculate_scraps_mathematically)
        self.adjust_text_sizes()

    def adjust_text_sizes(self):
        for label in [self.label_2, self.label_3, self.label_4,
                      self.label_5, self.label_rascr, self.label_7]:
            label.adjustSize()

    def load_orders(self):
        try:
            with self.db_manager as db:
                query = """
                SELECT o.id, o.status,
                       c.organization_name, e.last_name as manager
                FROM order_request o
                LEFT JOIN customer c ON o.customer_id = c.id
                LEFT JOIN employee e ON o.employee_id = e.id
                WHERE o.status = 'Подтвержден' or o.status = "Раскрой"
                GROUP BY o.id, c.organization_name, e.last_name, o.status
                """
                orders = db.execute_query(query)

                for i in reversed(range(self.verticalLayout_2.count())):
                    self.verticalLayout_2.itemAt(i).widget().deleteLater()

                for order in orders:
                    btn_text = (f"Заказ #{order['id']} | {order['organization_name']} | "
                                f"Статус: {order['status']}")
                    btn = QtWidgets.QPushButton(btn_text)
                    btn.setStyleSheet("""
                        QPushButton {
                            background-color: #f8f9fa;
                            border: 1px solid #dee2e6;
                            padding: 10px;
                            text-align: left;
                        }
                        QPushButton:hover { background-color: #e2e6ea; }
                    """)
                    btn.clicked.connect(lambda _, o=order: self.show_order_info(o))
                    self.verticalLayout_2.addWidget(btn)
        except Exception as e:
            self.show_error_message(f"Ошибка загрузки заказов: {str(e)}")

    def show_order_info(self, order):
        try:
            self.current_order = order
            with self.db_manager as db:
                fabric_query = """
                SELECT pm.supply_composition_id, pm.quantity, sc.width, sc.length, m.name as material_name, m.id as material_id
                FROM product_materials pm
                INNER JOIN supply_composition sc ON pm.supply_composition_id = sc.id
                INNER JOIN material m ON sc.material_id = m.id
                INNER JOIN order_composition oc ON pm.order_composition_id = oc.id
                WHERE oc.order_id = %s AND m.material_type_id != 2
                """
                fabric_data = db.execute_query(fabric_query, (order['id'],))
                fabrics = {}
                for fabric in fabric_data:
                    fabric_id = fabric['supply_composition_id']
                    if fabric_id not in fabrics:
                        fabrics[fabric_id] = {
                            'id': fabric['material_id'],
                            'width': float(fabric['width']),
                            'height': float(fabric['length']),
                            'quantity': int(fabric['quantity']),
                            'material_name': fabric['material_name']
                        }
                    else:
                        fabrics[fabric_id]['quantity'] += int(fabric['quantity'])
                fabric_info = "\n".join([
                    f"{data['material_name']} (id {data['id']}) #{fabric_id}: {data['width']}x{data['height']} см, {data['quantity']} шт"
                    for fabric_id, data in fabrics.items()
                ])
                self.label_3.setText(f"Доступные полотна ткани:\n{fabric_info}")
                self.label_3.adjustSize()

                order_query = """
                SELECT oc.id, p.name, oc.quantity, oc.width, oc.length
                FROM order_composition oc
                JOIN product p ON oc.product_id = p.id
                WHERE oc.order_id = %s
                """
                order_items = db.execute_query(order_query, (order['id'],))

                total_products = sum(item['quantity'] for item in order_items)

                self.label_2.setText(f"Требуется изделий: {total_products}")
                self.label_2.adjustSize()

                total_area = sum(item['width'] * item['length'] * item['quantity'] for item in order_items)
                self.label_5.setText(f"Общая площадь ткани: {total_area} см²")
                self.label_5.adjustSize()

                required_query = """
                SELECT m.name as hardware_name, SUM(pm.quantity) as required
                FROM product_materials pm
                JOIN supply_composition sc ON pm.supply_composition_id = sc.id
                JOIN material m ON sc.material_id = m.id
                JOIN material_type mt ON m.material_type_id = mt.id
                WHERE pm.order_composition_id IN (SELECT id FROM order_composition WHERE order_id = %s)
                  AND mt.name = 'Фурнитура'
                GROUP BY m.name
                """
                required_data = db.execute_query(required_query, (order['id'],))
                available_query = """
                SELECT m.name as hardware_name, SUM(sc.quantity) as available
                FROM supply_composition sc
                JOIN material m ON sc.material_id = m.id
                JOIN material_type mt ON m.material_type_id = mt.id
                WHERE mt.name = 'Фурнитура'
                GROUP BY m.name
                """
                available_data = db.execute_query(available_query)
                hardware_info_lines = []
                self.hardware_shortage = {}
                for req in required_data:
                    hardware_name = req['hardware_name']
                    required_qty = req['required']
                    available_qty = 0
                    for avail in available_data:
                        if avail['hardware_name'] == hardware_name:
                            available_qty = avail['available']
                            break
                    hardware_info_lines.append(
                        f"{hardware_name}: требуется {required_qty} шт, доступно {available_qty} шт"
                    )
                    if required_qty > available_qty:
                        self.hardware_shortage[hardware_name] = required_qty - available_qty
                self.label_4.setText("Фурнитура:\n" + "\n".join(hardware_info_lines))
                self.label_4.adjustSize()
        except Exception as e:
            self.show_error_message(f"Ошибка загрузки данных: {str(e)}")

    def pack_single_fabric(self, fabric_width, fabric_height, items):
        """
        Метод для расчёта раскроя с построением карты размещения изделий.
        Используется только для визуализации (calculate_cutting).
        """
        logging.debug(f"pack_single_fabric: fabric {fabric_width}x{fabric_height}, items: {items}")
        best_result = {'placements': [], 'used': [], 'area': 0}
        for rotation in [False, True]:
            temp_items = [item.copy() for item in items if item['quantity'] > 0]
            placements = []
            used = []
            max_cols = int(fabric_width // (temp_items[0]['width'] if not rotation else temp_items[0]['height']))
            for item in sorted(temp_items, key=lambda x: (-x['width'], -x['height'])):
                item_width = item['width'] if not rotation else item['height']
                item_height = item['height'] if not rotation else item['width']
                possible_count = int((fabric_width // item_width) * (fabric_height // item_height))
                count = min(possible_count, item['quantity'])
                if count > 0:
                    placements.append({
                        'x': 0,
                        'y': 0,
                        'width': item_width,
                        'height': item_height,
                        'count': count,
                        'name': item['name']
                    })
                    used.append({
                        'name': item['name'],
                        'count': count
                    })
                    item['quantity'] -= count
            total_area = sum(p['width'] * p['height'] * p['count'] for p in placements)
            if total_area > best_result['area']:
                best_result = {
                    'placements': placements,
                    'used': used,
                    'area': total_area
                }
        logging.debug(f"pack_single_fabric returning: {best_result}")
        return best_result['placements'], best_result['used']

    def create_cutting_map(self, fabric_id, width, height, placements, material_name):
        """
        Создаёт карту раскроя с визуальным отображением размещения изделий.
        """
        fig = Figure(figsize=(6, 4))
        canvas = FigureCanvas(fig)
        canvas.setFixedSize(600, 400)
        ax = fig.add_subplot(111)
        ax.set_title(f"{material_name} ({width}x{height} см)")
        ax.set_xlim(0, width)
        ax.set_ylim(0, height)
        ax.grid(True)
        ax.add_patch(plt.Rectangle((0, 0), width, height, fill=False, edgecolor='black', lw=2))
        for p in placements:
            for i in range(p['count']):
                cols = int(width // p['width'])
                row = i // cols
                col = i % cols
                x = col * p['width']
                y = row * p['height']
                rect = plt.Rectangle((x, y), p['width'], p['height'],
                                     edgecolor='blue', facecolor='lightblue', alpha=0.5)
                ax.add_patch(rect)
                ax.text(x + p['width'] / 2, y + p['height'] / 2,
                        f"{p['name']}\n{p['width']}x{p['height']}",
                        ha='center', va='center', fontsize=6)
        self.cutting_maps_container.add_cutting_map(canvas)

    def insert_scrap(self, prod_mat_id, scrap_length, scrap_width, scrap_area, db=None):
        """
        Вставляет запись обрезков в таблицу obrezki.
        Если передан параметр db, используется он, иначе создаётся новое соединение.
        """
        query = """
        INSERT INTO obrezki (prod_mat_id, length, width, remainder, creation_date, is_used)
        VALUES (%s, %s, %s, %s, CURDATE(), 0)
        """
        if db is None:
            with self.db_manager as db_conn:
                db_conn.execute_insert(query, (prod_mat_id, scrap_length, scrap_width, scrap_area))
        else:
            db.execute_insert(query, (prod_mat_id, scrap_length, scrap_width, scrap_area))
        logging.debug(f"Inserted scrap for prod_mat_id {prod_mat_id}: {scrap_length}x{scrap_width}, area {scrap_area}")

    def calculate_cutting(self):
        """
        Рассчитывает раскрой и генерирует карты размещения изделий.
        Этот метод используется для визуализации и не выполняет расчёт обрезков.
        """
        if not self.current_order:
            return
        try:
            self.cutting_maps_container.clear_maps()
            with self.db_manager as db:
                fabric_query = """
                SELECT pm.supply_composition_id, sc.width, sc.length, m.name as material_name, m.id as material_id
                FROM product_materials pm
                INNER JOIN supply_composition sc ON pm.supply_composition_id = sc.id
                INNER JOIN material m ON sc.material_id = m.id
                INNER JOIN order_composition oc ON pm.order_composition_id = oc.id
                WHERE oc.order_id = %s AND m.material_type_id != 2
                """
                fabric_data = db.execute_query(fabric_query, (self.current_order['id'],))
                fabrics_by_material = {}
                for fabric in fabric_data:
                    mat_name = fabric['material_name']
                    if mat_name not in fabrics_by_material:
                        fabrics_by_material[mat_name] = {
                            'id': fabric['material_id'],
                            'supply_composition_id': fabric['supply_composition_id'],
                            'width': float(fabric['width']),
                            'height': float(fabric['length']),
                            'material_name': mat_name
                        }
                logging.debug(f"Grouped fabrics: {fabrics_by_material}")

                order_query = """
                SELECT oc.id, p.name, oc.quantity, oc.width, oc.length, m.name as material_name
                FROM order_composition oc
                JOIN product p ON oc.product_id = p.id
                JOIN product_materials pm ON oc.id = pm.order_composition_id
                JOIN supply_composition sc ON pm.supply_composition_id = sc.id
                JOIN material m ON sc.material_id = m.id
                WHERE oc.order_id = %s AND m.material_type_id != 2
                """
                order_items = db.execute_query(order_query, (self.current_order['id'],))
                items_by_material = {}
                for item in order_items:
                    mat_name = item['material_name']
                    if mat_name not in items_by_material:
                        items_by_material[mat_name] = []
                    items_by_material[mat_name].append({
                        'name': item['name'],
                        'width': float(item['width']),
                        'height': float(item['length']),
                        'quantity': int(item['quantity'])
                    })
                logging.debug(f"Grouped order items: {items_by_material}")

                total_fabric_required = {}
                for material, items in items_by_material.items():
                    if material not in fabrics_by_material:
                        continue
                    fabric_info = fabrics_by_material[material]
                    fabric_width = fabric_info['width']
                    fabric_height = fabric_info['height']
                    supply_composition_id = fabric_info['supply_composition_id']
                    items_copy = [item.copy() for item in items]
                    fabric_required = 0
                    logging.debug(f"Calculating cutting for material {material} with items: {items_copy}")
                    while any(item['quantity'] > 0 for item in items_copy):
                        valid_items = [item for item in items_copy if item['quantity'] > 0]
                        placements, used = self.pack_single_fabric(fabric_width, fabric_height, valid_items)
                        if placements:
                            self.create_cutting_map(supply_composition_id, fabric_width, fabric_height, placements, material)
                            for u in used:
                                remaining = u['count']
                                for item in items_copy:
                                    if item['name'] == u['name'] and item['quantity'] > 0:
                                        if item['quantity'] >= remaining:
                                            item['quantity'] -= remaining
                                            remaining = 0
                                            break
                                        else:
                                            remaining -= item['quantity']
                                            item['quantity'] = 0
                            fabric_required += 1
                        else:
                            logging.debug(f"Cannot place remaining items for material {material} on one fabric.")
                            break
                    total_fabric_required[material] = {'id': fabrics_by_material[material]['id'], 'required': fabric_required}
                logging.debug(f"Total fabric required: {total_fabric_required}")

                assigned_query = """
                SELECT m.name as material_name, m.id as material_id, SUM(pm.quantity) as assigned
                FROM product_materials pm
                JOIN supply_composition sc ON pm.supply_composition_id = sc.id
                JOIN material m ON sc.material_id = m.id
                WHERE pm.order_composition_id IN (SELECT id FROM order_composition WHERE order_id = %s)
                GROUP BY m.id, m.name
                """
                assigned_data = db.execute_query(assigned_query, (self.current_order['id'],))
                assigned_dict = {row['material_name']: row['assigned'] for row in assigned_data}
                logging.debug(f"Assigned quantities: {assigned_dict}")

                self.fabric_shortage = {}
                for material, data in total_fabric_required.items():
                    assigned = assigned_dict.get(material, 0)
                    if assigned < data['required']:
                        self.fabric_shortage[material] = data['required'] - assigned
                logging.debug(f"Fabric shortage: {self.fabric_shortage}")

                result_text = "Необходимо полотен ткани для выполнения заказа:\n"
                for material, data in total_fabric_required.items():
                    result_text += f"{material} (id {data['id']}): {data['required']} шт\n"
                self.label_6.setText(result_text)
                self.label_6.adjustSize()

                self.check_and_prompt_supply_request()
        except Exception as e:
            self.show_error_message(f"Ошибка расчёта: {str(e)}")

    def calculate_scraps_mathematically(self):
        """
        Отдельный метод для математического расчёта обрезков.
        Расчёт производится по следующей формуле:
          total_item_area = сумма(ширина * длина * количество) для каждого изделия;
          fabric_area = ширина ткани * длина ткани;
          required_fabrics = ceil(total_item_area / (fabric_area * utilization));
          scrap_area = required_fabrics * fabric_area - total_item_area.
        Здесь utilization – коэффициент использования (например, 0.85).
        Результат записывается в таблицу obrezki.
        """
        if not self.current_order:
            return
        try:
            utilization = 0.85  # Предполагаемый коэффициент использования ткани
            with self.db_manager as db:
                # Изменён запрос: выбираем pm.id как prod_mat_id, который является корректным FK
                fabric_query = """
                SELECT pm.id as prod_mat_id, sc.width, sc.length, m.name as material_name
                FROM product_materials pm
                INNER JOIN supply_composition sc ON pm.supply_composition_id = sc.id
                INNER JOIN material m ON sc.material_id = m.id
                INNER JOIN order_composition oc ON pm.order_composition_id = oc.id
                WHERE oc.order_id = %s AND m.material_type_id != 2
                """
                fabric_data = db.execute_query(fabric_query, (self.current_order['id'],))
                fabrics_by_material = {}
                for fabric in fabric_data:
                    mat_name = fabric['material_name']
                    if mat_name not in fabrics_by_material:
                        fabrics_by_material[mat_name] = {
                            'prod_mat_id': fabric['prod_mat_id'],
                            'width': float(fabric['width']),
                            'height': float(fabric['length'])
                        }
                order_query = """
                SELECT oc.id, p.name, oc.quantity, oc.width, oc.length, m.name as material_name
                FROM order_composition oc
                JOIN product p ON oc.product_id = p.id
                JOIN product_materials pm ON oc.id = pm.order_composition_id
                JOIN supply_composition sc ON pm.supply_composition_id = sc.id
                JOIN material m ON sc.material_id = m.id
                WHERE oc.order_id = %s AND m.material_type_id != 2
                """
                order_items = db.execute_query(order_query, (self.current_order['id'],))
                items_by_material = {}
                for item in order_items:
                    mat_name = item['material_name']
                    if mat_name not in items_by_material:
                        items_by_material[mat_name] = []
                    items_by_material[mat_name].append({
                        'width': float(item['width']),
                        'height': float(item['length']),
                        'quantity': int(item['quantity'])
                    })
                for material, items in items_by_material.items():
                    if material not in fabrics_by_material:
                        continue
                    fabric_info = fabrics_by_material[material]
                    fabric_area = fabric_info['width'] * fabric_info['height']
                    total_item_area = sum(item['width'] * item['height'] * item['quantity'] for item in items)
                    required_fabrics = math.ceil(total_item_area / (fabric_area * utilization))
                    scrap_area = required_fabrics * fabric_area - total_item_area
                    logging.debug(f"Material {material}: total_item_area = {total_item_area}, required_fabrics = {required_fabrics}, scrap_area = {scrap_area}")
                    if scrap_area > 5:
                        # Используем корректный prod_mat_id
                        self.insert_scrap(fabric_info['prod_mat_id'], fabric_info['height'], fabric_info['width'], scrap_area, db=db)
            info_box = QtWidgets.QMessageBox(self)
            info_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
            info_box.setWindowTitle("Обрезки рассчитаны")
            info_box.setText("Обрезки рассчитаны математически и внесены в таблицу obrezki.")
            info_box.setStyleSheet("QLabel { color: white; } QPushButton { color: white; }")
            info_box.exec()
        except Exception as e:
            self.show_error_message(f"Ошибка расчёта обрезков: {str(e)}")

    def check_and_prompt_supply_request(self):
        self.shortage_data = {}
        for material, shortage in self.fabric_shortage.items():
            if shortage > 0:
                self.shortage_data[material] = shortage
        for material, shortage in self.hardware_shortage.items():
            if shortage > 0:
                self.shortage_data[material] = shortage
        with self.db_manager as db:
            if not self.shortage_data:
                db.execute_query("UPDATE order_request SET status = %s WHERE id = %s", ("Готово в цеху", self.current_order['id']))
                info_box = QtWidgets.QMessageBox(self)
                info_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
                info_box.setWindowTitle("Заказ готов")
                info_box.setText("Все материалы есть. Статус заказа изменен на 'Готово в цеху'.")
                info_box.setStyleSheet("QLabel { color: white; } QPushButton { color: white; }")
                info_box.exec()
            else:
                all_available = True
                for material, shortage in self.shortage_data.items():
                    result = db.execute_query(
                        "SELECT SUM(remainder) as total_remainder FROM supply_composition sc JOIN material m ON sc.material_id = m.id WHERE m.name = %s",
                        (material,)
                    )
                    total_remainder = result[0]['total_remainder'] if result and result[0]['total_remainder'] is not None else 0
                    if total_remainder < shortage:
                        all_available = False
                        break
                if all_available:
                    for material, shortage in self.shortage_data.items():
                        needed = shortage
                        rows = db.execute_query(
                            "SELECT sc.id, sc.remainder FROM supply_composition sc JOIN material m ON sc.material_id = m.id WHERE m.name = %s AND sc.remainder > 0 ORDER BY sc.id",
                            (material,)
                        )
                        for row in rows:
                            if needed <= 0:
                                break
                            available = row['remainder']
                            transfer_amount = min(available, needed)
                            oc_res = db.execute_query(
                                "SELECT pm.id, oc.id as oc_id FROM order_composition oc JOIN product_materials pm ON oc.id = pm.order_composition_id JOIN supply_composition sc ON pm.supply_composition_id = sc.id JOIN material m ON sc.material_id = m.id WHERE oc.order_id = %s AND m.name = %s LIMIT 1",
                                (self.current_order['id'], material)
                            )
                            if oc_res:
                                pm_id = oc_res[0]['id']
                                db.execute_query(
                                    "UPDATE product_materials SET quantity = quantity + %s WHERE id = %s",
                                    (transfer_amount, pm_id)
                                )
                            else:
                                oc_res = db.execute_query(
                                    "SELECT id FROM order_composition WHERE order_id = %s LIMIT 1",
                                    (self.current_order['id'],)
                                )
                                if oc_res:
                                    oc_id = oc_res[0]['id']
                                    db.execute_insert(
                                        "INSERT INTO product_materials (order_composition_id, supply_composition_id, quantity, cost) VALUES (%s, %s, %s, NULL)",
                                        (oc_id, row['id'], transfer_amount)
                                    )
                            db.execute_query("UPDATE supply_composition SET remainder = remainder - %s WHERE id = %s", (transfer_amount, row['id']))
                            needed -= transfer_amount
                    db.execute_query("UPDATE order_request SET status = %s WHERE id = %s", ("Раскрой", self.current_order['id']))
                    info_box = QtWidgets.QMessageBox(self)
                    info_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
                    info_box.setWindowTitle("Материалы переведены")
                    info_box.setText("Материалы из остатка поставок добавлены к заказу. Статус заказа изменен на 'Раскрой'.")
                    info_box.setStyleSheet("QLabel { color: white; } QPushButton { color: white; }")
                    info_box.exec()
                else:
                    details = "\n".join([f"{k}: не хватает {v} шт" for k, v in self.shortage_data.items()])
                    msg_box = QtWidgets.QMessageBox(self)
                    msg_box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
                    msg_box.setWindowTitle("Недостаточно материалов")
                    msg_box.setText("Для выполнения заказа не хватает следующих материалов:\n" + details)
                    msg_box.setStyleSheet("QLabel { color: white; } QPushButton { color: white; }")
                    create_btn = msg_box.addButton("Создать заявку", QtWidgets.QMessageBox.ButtonRole.AcceptRole)
                    cancel_btn = msg_box.addButton("Отмена", QtWidgets.QMessageBox.ButtonRole.RejectRole)
                    msg_box.exec()
                    if msg_box.clickedButton() == create_btn:
                        self.create_supply_requests()

    def create_supply_requests(self):
        try:
            with self.db_manager as db:
                for material_name, shortage in self.shortage_data.items():
                    dialog = SupplyRequestDialog(material_name, shortage, self)
                    if dialog.exec() == QtWidgets.QDialog.DialogCode.Accepted:
                        length, width = dialog.get_values()
                        if length <= 0 or width <= 0:
                            self.show_error_message(f"Некорректные размеры для {material_name}.")
                            continue
                    else:
                        continue
                    mat_res = db.execute_query("SELECT id FROM material WHERE name = %s", (material_name,))
                    if not mat_res:
                        continue
                    material_id = mat_res[0]['id']
                    supply_id = db.execute_insert(
                        "INSERT INTO supply (employee_id, supplier_id, total_amount, date) VALUES (%s, %s, %s, CURDATE())",
                        (1, None, 0)
                    )
                    sc_id = db.execute_insert(
                        "INSERT INTO supply_composition (supply_id, material_id, quantity, length, width, cost, unit_quantity, status, location_id, remainder) VALUES (%s, %s, %s, %s, %s, NULL, '6', %s, NULL, '0')",
                        (supply_id, material_id, shortage, length, width, "Ждёт подтверждения") # (, shortage)
                    )
                    oc_res = db.execute_query(
                        "SELECT id FROM order_composition WHERE order_id = %s LIMIT 1",
                        (self.current_order['id'],)
                    )
                    if oc_res:
                        oc_id = oc_res[0]['id']
                        db.execute_insert(
                            "INSERT INTO product_materials (order_composition_id, supply_composition_id, quantity, cost) VALUES (%s, %s, '0', NULL)",
                            (oc_id, sc_id)
                        )
                db.execute_query("UPDATE order_request SET status = %s WHERE id = %s",
                                 ("Заказ материалов", self.current_order['id']))
            info_box = QtWidgets.QMessageBox(self)
            info_box.setIcon(QtWidgets.QMessageBox.Icon.Information)
            info_box.setWindowTitle("Заявка создана")
            info_box.setText("Заявка на материалы успешно создана.")
            info_box.setStyleSheet("QLabel { color: white; } QPushButton { color: white; }")
            info_box.exec()
        except Exception as e:
            self.show_error_message(f"Ошибка создания заявки: {str(e)}")

    def show_error_message(self, text):
        msg = QtWidgets.QMessageBox(self)
        msg.setIcon(QtWidgets.QMessageBox.Icon.Critical)
        msg.setText("Ошибка")
        msg.setInformativeText(text)
        msg.setWindowTitle("Ошибка")
        msg.setStyleSheet("QLabel { color: white; } QPushButton { color: white; }")
        msg.exec()

    def show_order_page(self):
        self.stackedWidget.setCurrentIndex(0)

if __name__ == "__main__":
    app = QtWidgets.QApplication(sys.argv)
    window = Main()
    window.show()
    sys.exit(app.exec())
