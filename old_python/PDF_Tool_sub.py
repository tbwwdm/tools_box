# -*- coding: utf-8 -*-
"""
PDF 工具集：合并、拆分、A4 多页拼版、页面编辑。
"""
import math
import os
import sys
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Qt, QSize, QMimeData, QRect
from PySide6.QtGui import QColor, QDrag, QFont, QIcon, QImage, QPainter, QPixmap, QTransform
from PySide6.QtWidgets import (
    QApplication,
    QDialog,
    QFileDialog,
    QFrame,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QListView,
    QListWidget,
    QListWidgetItem,
    QMessageBox,
    QPushButton,
    QScrollArea,
    QSpinBox,
    QStyle,
    QStyledItemDelegate,
    QStyleOptionViewItem,
    QTextEdit,
    QToolButton,
    QVBoxLayout,
    QWidget,
)


A4_PORTRAIT = (595.27559055, 841.88976378)
A4_LANDSCAPE = (841.88976378, 595.27559055)


def _import_fitz():
    errors = []
    try:
        import pymupdf
        return pymupdf
    except ImportError as exc:
        errors.append(f"pymupdf: {exc}")
    try:
        import fitz
        return fitz
    except ImportError as exc:
        errors.append(f"fitz: {exc}")
    exe = getattr(sys, "executable", "")
    detail = "; ".join(errors)
    raise RuntimeError(
        "缺少 PyMuPDF 依赖，PDF 工具无法处理文件。\n"
        "请在当前运行环境安装：python -m pip install pymupdf\n"
        f"当前运行环境：{exe}\n"
        f"导入详情：{detail}"
    )


def merge_pdfs(input_files, output_file):
    """将多个 PDF 按列表顺序合并为一个 PDF。"""
    fitz = _import_fitz()
    files = [Path(p) for p in input_files if str(p).strip()]
    if not files:
        raise ValueError("请至少选择一个 PDF 文件")
    for pdf in files:
        if not pdf.exists():
            raise FileNotFoundError(str(pdf))

    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)
    result = fitz.open()
    try:
        for pdf in files:
            with fitz.open(str(pdf)) as doc:
                result.insert_pdf(doc)
        result.save(str(output), garbage=4, deflate=True)
    finally:
        result.close()
    return output


def split_pdf(input_file, output_dir, pages_per_file=1, prefix=None):
    """将一个 PDF 按 pages_per_file 页一份拆分为多个 PDF。"""
    fitz = _import_fitz()
    src = Path(input_file)
    if not src.exists():
        raise FileNotFoundError(str(src))
    if pages_per_file < 1:
        raise ValueError("每个文件页数必须大于 0")

    out_dir = Path(output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    prefix = prefix or src.stem
    outputs = []

    with fitz.open(str(src)) as doc:
        total = doc.page_count
        for start in range(0, total, pages_per_file):
            end = min(start + pages_per_file, total)
            out = out_dir / f"{prefix}_{start + 1:03d}-{end:03d}.pdf"
            part = fitz.open()
            try:
                part.insert_pdf(doc, from_page=start, to_page=end - 1)
                part.save(str(out), garbage=4, deflate=True)
            finally:
                part.close()
            outputs.append(out)
    return outputs


def nup_pdf_to_a4(
    input_file,
    output_file,
    pages_per_sheet=4,
    rows=2,
    landscape=True,
    margin=5.0,
):
    """将 PDF 按指定页数拼接到 A4 纸上，按 rows 行排列，列数自动计算。"""
    fitz = _import_fitz()
    src = Path(input_file)
    if not src.exists():
        raise FileNotFoundError(str(src))
    if pages_per_sheet < 1:
        raise ValueError("每张 A4 拼接页数必须大于 0")
    if rows < 1 or rows > pages_per_sheet:
        raise ValueError("行数必须大于 0 且不能超过每张拼接页数")
    if margin < 0:
        raise ValueError("边距不能为负数")

    cols = math.ceil(pages_per_sheet / rows)
    page_w, page_h = A4_LANDSCAPE if landscape else A4_PORTRAIT
    slot_w = page_w / cols
    slot_h = page_h / rows
    if slot_w <= 2 * margin or slot_h <= 2 * margin:
        raise ValueError("边距过大，当前拼版格子无法放入页面")

    output = Path(output_file)
    output.parent.mkdir(parents=True, exist_ok=True)

    with fitz.open(str(src)) as doc:
        result = fitz.open()
        try:
            for start in range(0, doc.page_count, pages_per_sheet):
                sheet = result.new_page(width=page_w, height=page_h)
                stop = min(start + pages_per_sheet, doc.page_count)
                for offset, page_index in enumerate(range(start, stop)):
                    row = offset // cols
                    col = offset % cols
                    x0 = col * slot_w + margin
                    y0 = row * slot_h + margin
                    rect = fitz.Rect(
                        x0,
                        y0,
                        x0 + slot_w - 2 * margin,
                        y0 + slot_h - 2 * margin,
                    )
                    sheet.show_pdf_page(
                        rect,
                        doc,
                        page_index,
                        keep_proportion=True,
                        overlay=True,
                    )
            result.save(str(output), garbage=4, deflate=True)
        finally:
            result.close()
    return output


def edit_pdf(input_file, output_file, page_specs, content_edits_by_row=None):
    """按页面列表重排、删除并旋转 PDF 页面，输出到新文件。"""
    fitz = _import_fitz()
    src = Path(input_file)
    if not src.exists():
        raise FileNotFoundError(str(src))
    output = Path(output_file)
    if src.resolve() == output.resolve():
        raise ValueError("输出文件不能和输入文件相同，请另存为新 PDF。")
    if not page_specs:
        raise ValueError("请至少保留一个页面")

    output.parent.mkdir(parents=True, exist_ok=True)
    content_edits_by_row = content_edits_by_row or {}
    with fitz.open(str(src)) as doc:
        result = fitz.open()
        try:
            for output_row, spec in enumerate(page_specs):
                page_index = int(spec.get("page_index", -1))
                rotation_delta = int(spec.get("rotation", 0)) % 360
                if page_index < 0 or page_index >= doc.page_count:
                    raise ValueError(f"页面序号超出范围：{page_index + 1}")
                result.insert_pdf(doc, from_page=page_index, to_page=page_index)
                inserted = result.load_page(result.page_count - 1)
                for edit in content_edits_by_row.get(output_row, []):
                    if edit.get("type") == "whiteout":
                        rect = fitz.Rect(*edit["rect"])
                        inserted.draw_rect(rect, color=(1, 1, 1), fill=(1, 1, 1), overlay=True)
                    elif edit.get("type") == "text":
                        text = str(edit.get("text", "")).strip()
                        if not text:
                            continue
                        inserted.insert_text(
                            (float(edit["x"]), float(edit["y"])),
                            text,
                            fontsize=float(edit.get("font_size", 14)),
                            color=(0, 0, 0),
                            overlay=True,
                        )
                source_rotation = doc.load_page(page_index).rotation
                inserted.set_rotation((source_rotation + rotation_delta) % 360)
            result.save(str(output), garbage=4, deflate=True)
        finally:
            result.close()
    return output


class PdfWorker(QObject):
    finished = Signal(object)
    failed = Signal(str)

    def __init__(self, func, *args, **kwargs):
        super().__init__()
        self.func = func
        self.args = args
        self.kwargs = kwargs

    def run(self):
        try:
            self.finished.emit(self.func(*self.args, **self.kwargs))
        except Exception as exc:
            self.failed.emit(str(exc))


class PdfDropListWidget(QListWidget):
    files_dropped = Signal(list)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setDragDropMode(QListWidget.DropOnly)
        self.setDefaultDropAction(Qt.CopyAction)
        self.setProperty("dropHint", "支持拖拽多个 PDF 到此处")

    def dragEnterEvent(self, event):
        if self._event_pdf_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._event_pdf_files(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        files = self._event_pdf_files(event)
        if not files:
            event.ignore()
            return
        self.files_dropped.emit(files)
        event.acceptProposedAction()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count():
            return
        hint = self.property("dropHint") or "支持拖拽 PDF 到此处"
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#8a98a8"))
        painter.drawText(self.viewport().rect(), Qt.AlignCenter, hint)

    @staticmethod
    def _event_pdf_files(event):
        mime = event.mimeData()
        if not mime.hasUrls():
            return []
        files = []
        for url in mime.urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(".pdf") and Path(path).is_file():
                files.append(path)
        return files


class PdfMergeListWidget(PdfDropListWidget):
    preview_requested = Signal(str)
    expand_requested = Signal(str)

    INTERNAL_REORDER_MIME = "application/x-pdf-merge-reorder"
    THUMB_SIZE = QSize(190, 140)
    GRID_SIZE = QSize(230, 215)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._browse_mode = False
        self._overlay = QFrame(self.viewport())
        self._overlay.setObjectName("pdfItemOverlay")
        self._overlay.setStyleSheet(
            """
            QFrame#pdfItemOverlay {
                background:#ffffff;
                border:1px solid #a9b4bf;
                border-radius:4px;
            }
            QToolButton {
                border:none;
                padding:4px;
                color:#4b5563;
                font-size:12px;
            }
            QToolButton:hover { background:#edf5ff; color:#0984e3; }
            """
        )
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setContentsMargins(4, 4, 4, 4)
        overlay_layout.setSpacing(4)

        self._delete_btn = QToolButton(self._overlay)
        self._delete_btn.setToolTip("删除选中的 PDF")
        self._delete_btn.setText("删除")
        self._delete_btn.setIcon(self.style().standardIcon(QStyle.SP_TrashIcon))
        self._preview_btn = QToolButton(self._overlay)
        self._preview_btn.setToolTip("放大预览")
        self._preview_btn.setText("放大")
        self._preview_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self._expand_btn = QToolButton(self._overlay)
        self._expand_btn.setToolTip("展开多页预览")
        self._expand_btn.setText("展开")
        self._expand_btn.setIcon(self.style().standardIcon(QStyle.SP_TitleBarUnshadeButton))
        for btn in (self._delete_btn, self._preview_btn, self._expand_btn):
            btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
            overlay_layout.addWidget(btn)

        self._overlay.hide()
        self._drop_indicator = QFrame(self.viewport())
        self._drop_indicator.setObjectName("pdfDropIndicator")
        self._drop_indicator.setStyleSheet(
            """
            QFrame#pdfDropIndicator {
                background:rgba(9, 132, 227, 90);
                border:1px solid rgba(9, 132, 227, 180);
                border-radius:3px;
            }
            """
        )
        self._drop_indicator.hide()
        self.itemSelectionChanged.connect(self._update_overlay)
        self.itemDoubleClicked.connect(self._preview_double_clicked_item)
        self._delete_btn.clicked.connect(self.remove_current_item)
        self._preview_btn.clicked.connect(self._preview_current_item)
        self._expand_btn.clicked.connect(self._expand_current_item)
        self.setWordWrap(True)
        self.set_browse_mode(True)

    def set_browse_mode(self, enabled):
        self._browse_mode = enabled
        self.setDragEnabled(enabled)
        self.setAcceptDrops(True)
        self.setDropIndicatorShown(enabled)
        self.setDefaultDropAction(Qt.MoveAction if enabled else Qt.CopyAction)
        self.setDragDropMode(QListWidget.DragDrop if enabled else QListWidget.DropOnly)
        self.setDragDropOverwriteMode(False)
        self.setMovement(QListView.Snap if enabled else QListView.Static)
        self.setResizeMode(QListView.Adjust)
        self.setWrapping(enabled)
        self.setViewMode(QListView.IconMode if enabled else QListView.ListMode)
        self.setIconSize(self.THUMB_SIZE if enabled else QSize(0, 0))
        self.setGridSize(self.GRID_SIZE if enabled else QSize())
        self.setSpacing(14 if enabled else 2)
        self.setProperty(
            "dropHint",
            "拖拽 PDF 到此处，浏览模式支持拖动缩略图排序"
            if enabled
            else "支持拖拽多个 PDF 到此处",
        )
        for row in range(self.count()):
            self._refresh_item(self.item(row))
        self._drop_indicator.hide()
        self._update_overlay()
        self.viewport().update()

    def add_pdf(self, path):
        item = QListWidgetItem()
        item.setData(Qt.UserRole, str(path))
        item.setData(Qt.UserRole + 1, self.pdf_page_count(path))
        item.setToolTip(str(path))
        item.setFlags(item.flags() | Qt.ItemIsDragEnabled | Qt.ItemIsDropEnabled)
        self._refresh_item(item)
        self.addItem(item)
        return item

    def contains_path(self, path):
        needle = str(path)
        for row in range(self.count()):
            if self.item(row).data(Qt.UserRole) == needle:
                return True
        return False

    def file_paths(self):
        return [self.item(row).data(Qt.UserRole) for row in range(self.count())]

    def remove_current_item(self):
        item = self.currentItem()
        if item is None:
            return
        self.takeItem(self.row(item))
        self._update_overlay()

    def remove_selected_items(self):
        rows = sorted((self.row(item) for item in self.selectedItems()), reverse=True)
        for row in rows:
            self.takeItem(row)
        self._update_overlay()

    def clear(self):
        super().clear()
        self._overlay.hide()
        self._drop_indicator.hide()

    def dragEnterEvent(self, event):
        if self._event_pdf_files(event):
            event.acceptProposedAction()
            return
        if self._browse_mode and self._is_internal_item_drag(event):
            self._show_drop_indicator(event)
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if self._event_pdf_files(event):
            event.acceptProposedAction()
            return
        if self._browse_mode and self._is_internal_item_drag(event):
            self._show_drop_indicator(event)
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        super().dragMoveEvent(event)

    def dropEvent(self, event):
        files = self._event_pdf_files(event)
        if files:
            self.files_dropped.emit(files)
            event.acceptProposedAction()
            return
        if self._browse_mode and self._is_internal_item_drag(event):
            self._move_selected_to_drop_position(event)
            self._drop_indicator.hide()
            event.setDropAction(Qt.MoveAction)
            event.accept()
            return
        super().dropEvent(event)
        self._drop_indicator.hide()
        self._update_overlay()

    def supportedDropActions(self):
        return Qt.CopyAction | Qt.MoveAction

    def dragLeaveEvent(self, event):
        self._drop_indicator.hide()
        super().dragLeaveEvent(event)

    def startDrag(self, supported_actions):
        if not self._browse_mode or not self.selectedItems():
            super().startDrag(supported_actions)
            return

        self._overlay.hide()
        self._drop_indicator.hide()

        drag = QDrag(self)
        mime = QMimeData()
        mime.setData(self.INTERNAL_REORDER_MIME, b"1")
        drag.setMimeData(mime)

        current = self.currentItem() or self.selectedItems()[0]
        icon = current.icon()
        if not icon.isNull():
            drag.setPixmap(icon.pixmap(QSize(120, 90)))

        drag.exec(Qt.MoveAction, Qt.MoveAction)
        self._drop_indicator.hide()
        self._update_overlay()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._drop_indicator.hide()
        self._update_overlay()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._drop_indicator.hide()
        self._update_overlay()

    def _refresh_item(self, item):
        path = item.data(Qt.UserRole)
        name = Path(path).name if path else ""
        if self._browse_mode:
            item.setText(name)
            item.setIcon(QIcon(self.render_pdf_thumbnail(path, self.THUMB_SIZE)))
            item.setTextAlignment(Qt.AlignHCenter)
            item.setSizeHint(self.GRID_SIZE)
        else:
            item.setText(path or name)
            item.setIcon(QIcon())
            item.setTextAlignment(Qt.AlignVCenter | Qt.AlignLeft)
            item.setSizeHint(QSize())

    def _preview_current_item(self):
        item = self.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if path:
            self.preview_requested.emit(path)

    def _preview_double_clicked_item(self, item):
        self.setCurrentItem(item)
        self._preview_current_item()

    def _expand_current_item(self):
        item = self.currentItem()
        if item is None:
            return
        path = item.data(Qt.UserRole)
        if path:
            self.expand_requested.emit(path)

    def _is_internal_item_drag(self, event):
        if not self.selectedItems():
            return False
        source = event.source() if hasattr(event, "source") else None
        if source is self:
            return True
        mime = event.mimeData()
        return bool(mime and mime.hasFormat(self.INTERNAL_REORDER_MIME))

    def _move_selected_to_drop_position(self, event):
        rows = sorted({self.row(item) for item in self.selectedItems()})
        if not rows:
            return

        target_row = self._drop_target_row(event)
        moving = []
        current_path = self.currentItem().data(Qt.UserRole) if self.currentItem() else None
        for row in reversed(rows):
            moving.insert(0, self.takeItem(row))
            if row < target_row:
                target_row -= 1

        target_row = max(0, min(target_row, self.count()))
        for offset, item in enumerate(moving):
            self.insertItem(target_row + offset, item)
            item.setSelected(True)

        if current_path:
            for row in range(self.count()):
                item = self.item(row)
                if item.data(Qt.UserRole) == current_path:
                    self.setCurrentItem(item)
                    break
        else:
            self.setCurrentItem(moving[0])
        self._update_overlay()

    def _drop_target_row(self, event):
        pos = event.position().toPoint() if hasattr(event, "position") else event.pos()
        for row in range(self.count()):
            rect = self.visualItemRect(self.item(row))
            if not rect.isValid():
                continue
            if pos.y() < rect.top():
                return row
            if rect.top() <= pos.y() <= rect.bottom() and pos.x() < rect.center().x():
                return row
        return self.count()

    def _show_drop_indicator(self, event):
        geometry = self._drop_indicator_geometry(self._drop_target_row(event))
        if geometry is None:
            self._drop_indicator.hide()
            return
        self._drop_indicator.setGeometry(*geometry)
        self._drop_indicator.raise_()
        self._drop_indicator.show()

    def _drop_indicator_geometry(self, target_row):
        if self.count() == 0:
            return None

        line_width = 8
        if target_row < self.count():
            rect = self.visualItemRect(self.item(target_row))
            if not rect.isValid():
                return None
            x = max(0, rect.left() - line_width - 3)
        else:
            rect = self.visualItemRect(self.item(self.count() - 1))
            if not rect.isValid():
                return None
            x = min(self.viewport().width() - line_width, rect.right() + 10)

        y = rect.top() + 10
        height = max(74, rect.height() - 20)
        return x, y, line_width, height

    def _update_overlay(self):
        if not self._browse_mode or self.currentItem() is None:
            self._overlay.hide()
            return
        rect = self.visualItemRect(self.currentItem())
        if not rect.isValid() or rect.bottom() < 0 or rect.top() > self.viewport().height():
            self._overlay.hide()
            return
        page_count = self.currentItem().data(Qt.UserRole + 1) or 1
        show_expand = page_count > 1
        self._expand_btn.setVisible(show_expand)
        self._overlay.setFixedSize(58, 138 if show_expand else 92)
        x = max(rect.left() + 6, rect.right() - self._overlay.width() - 8)
        y = rect.top() + 8
        self._overlay.move(x, y)
        self._overlay.raise_()
        self._overlay.show()

    @staticmethod
    def pdf_page_count(path):
        try:
            fitz = _import_fitz()
            with fitz.open(str(path)) as doc:
                return doc.page_count
        except Exception:
            return 1

    @staticmethod
    def render_pdf_thumbnail(path, target_size, page_index=0):
        pixmap = QPixmap(target_size)
        pixmap.fill(QColor("#f8fafc"))
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#c5ced8"))
        painter.setBrush(QColor("#ffffff"))
        page_rect = pixmap.rect().adjusted(12, 8, -12, -8)
        painter.drawRect(page_rect)
        painter.setPen(QColor("#8a98a8"))
        painter.drawText(page_rect, Qt.AlignCenter, "PDF")
        painter.end()

        try:
            fitz = _import_fitz()
            with fitz.open(str(path)) as doc:
                if doc.page_count < 1:
                    return pixmap
                page_index = max(0, min(page_index, doc.page_count - 1))
                page = doc.load_page(page_index)
                rect = page.rect
                scale = min(
                    target_size.width() / max(rect.width, 1),
                    target_size.height() / max(rect.height, 1),
                    3,
                )
                rendered = page.get_pixmap(matrix=fitz.Matrix(scale, scale), alpha=False)
                fmt = QImage.Format_RGB888 if rendered.n < 4 else QImage.Format_RGBA8888
                image = QImage(rendered.samples, rendered.width, rendered.height, rendered.stride, fmt).copy()
                page_pixmap = QPixmap.fromImage(image).scaled(
                    target_size,
                    Qt.KeepAspectRatio,
                    Qt.SmoothTransformation,
                )
        except Exception:
            return pixmap

        pixmap.fill(QColor("#f8fafc"))
        painter = QPainter(pixmap)
        x = (target_size.width() - page_pixmap.width()) // 2
        y = (target_size.height() - page_pixmap.height()) // 2
        painter.drawPixmap(x, y, page_pixmap)
        painter.setPen(QColor("#d0d7de"))
        painter.drawRect(x, y, page_pixmap.width() - 1, page_pixmap.height() - 1)
        painter.end()
        return pixmap


class NoNativeSelectionDelegate(QStyledItemDelegate):
    def paint(self, painter, option, index):
        clean = QStyleOptionViewItem(option)
        clean.state &= ~QStyle.State_Selected
        clean.state &= ~QStyle.State_HasFocus
        clean.state &= ~QStyle.State_MouseOver
        super().paint(painter, clean, index)


class PdfPagePreviewListWidget(QListWidget):
    preview_page_requested = Signal(str, int)

    PAGE_SIZE = QSize(170, 220)
    TILE_SIZE = QSize(190, 258)
    GRID_SIZE = QSize(210, 280)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_path = ""
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWrapping(True)
        self.setIconSize(self.TILE_SIZE)
        self.setGridSize(self.GRID_SIZE)
        self.setSpacing(18)
        self.setWordWrap(True)
        self.setSelectionMode(QListWidget.SingleSelection)
        self.setItemDelegate(NoNativeSelectionDelegate(self))
        self.setStyleSheet(
            """
            QListWidget {
                background:#eeeeee;
                border:1px solid #dfe6e9;
                padding:18px;
                font-size:13px;
            }
            QListWidget::item {
                background:transparent;
                border:none;
                color:#2d3436;
            }
            QListWidget::item:selected {
                background:transparent;
                border:none;
                color:#2d3436;
            }
            QListWidget::item:selected:active,
            QListWidget::item:selected:!active,
            QListWidget::item:hover,
            QListWidget::item:focus {
                background:transparent;
                border:none;
                outline:none;
            }
            """
        )

        self._overlay = QFrame(self.viewport())
        self._overlay.setObjectName("pdfPageOverlay")
        self._overlay.setFixedSize(58, 48)
        self._overlay.setStyleSheet(
            """
            QFrame#pdfPageOverlay {
                background:#ffffff;
                border:1px solid #a9b4bf;
                border-radius:4px;
            }
            QToolButton {
                border:none;
                padding:4px;
                color:#4b5563;
                font-size:12px;
            }
            QToolButton:hover { background:#edf5ff; color:#0984e3; }
            """
        )
        overlay_layout = QVBoxLayout(self._overlay)
        overlay_layout.setContentsMargins(4, 4, 4, 4)
        self._preview_btn = QToolButton(self._overlay)
        self._preview_btn.setToolTip("放大预览")
        self._preview_btn.setText("放大")
        self._preview_btn.setIcon(self.style().standardIcon(QStyle.SP_FileDialogContentsView))
        self._preview_btn.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
        overlay_layout.addWidget(self._preview_btn)
        self._overlay.hide()

        self.itemSelectionChanged.connect(self._update_overlay)
        self.itemDoubleClicked.connect(self._preview_double_clicked_page)
        self._preview_btn.clicked.connect(self._preview_current_page)

    def load_pdf(self, path):
        self._pdf_path = str(path)
        self.clear()
        page_count = PdfMergeListWidget.pdf_page_count(path)
        for page_index in range(page_count):
            item = QListWidgetItem("")
            item.setData(Qt.UserRole, page_index)
            item.setIcon(QIcon(self._render_page_tile(path, page_index)))
            item.setTextAlignment(Qt.AlignHCenter)
            item.setSizeHint(self.GRID_SIZE)
            item.setToolTip(f"第 {page_index + 1} 页")
            self.addItem(item)
        self._overlay.hide()

    def clear(self):
        super().clear()
        if hasattr(self, "_overlay"):
            self._overlay.hide()

    def paintEvent(self, event):
        super().paintEvent(event)
        self._paint_selected_frame()

    def resizeEvent(self, event):
        super().resizeEvent(event)
        self._update_overlay()

    def scrollContentsBy(self, dx, dy):
        super().scrollContentsBy(dx, dy)
        self._update_overlay()

    def _paint_selected_frame(self):
        item = self.currentItem()
        if item is None:
            return
        rect = self.visualItemRect(item)
        if not rect.isValid() or rect.bottom() < 0 or rect.top() > self.viewport().height():
            return
        frame_width = min(self.TILE_SIZE.width() + 8, rect.width() - 6)
        frame_height = min(self.TILE_SIZE.height() + 8, rect.height() - 6)
        frame_left = rect.left() + (rect.width() - frame_width) // 2
        frame = QRect(frame_left, rect.top() + 3, frame_width, frame_height)
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#0984e3"))
        painter.setBrush(QColor(219, 234, 254, 90))
        painter.drawRoundedRect(frame, 4, 4)
        painter.end()

    def _render_page_tile(self, path, page_index):
        pixmap = QPixmap(self.TILE_SIZE)
        pixmap.fill(QColor("#eeeeee"))

        page_pixmap = PdfMergeListWidget.render_pdf_thumbnail(path, self.PAGE_SIZE, page_index)
        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        x = (self.TILE_SIZE.width() - page_pixmap.width()) // 2
        painter.drawPixmap(x, 0, page_pixmap)
        painter.setPen(QColor("#2d3436"))
        painter.drawText(
            0,
            self.PAGE_SIZE.height() + 8,
            self.TILE_SIZE.width(),
            self.TILE_SIZE.height() - self.PAGE_SIZE.height() - 8,
            Qt.AlignHCenter | Qt.AlignTop,
            str(page_index + 1),
        )
        painter.end()
        return pixmap

    def _preview_current_page(self):
        item = self.currentItem()
        if item is None or not self._pdf_path:
            return
        self.preview_page_requested.emit(self._pdf_path, item.data(Qt.UserRole))

    def _preview_double_clicked_page(self, item):
        self.setCurrentItem(item)
        self._preview_current_page()

    def _update_overlay(self):
        item = self.currentItem()
        if item is None:
            self._overlay.hide()
            self.viewport().update()
            return
        rect = self.visualItemRect(item)
        if not rect.isValid() or rect.bottom() < 0 or rect.top() > self.viewport().height():
            self._overlay.hide()
            self.viewport().update()
            return
        x = max(rect.left() + 6, rect.right() - self._overlay.width() - 8)
        y = rect.top() + 8
        self._overlay.move(x, y)
        self._overlay.raise_()
        self._overlay.show()
        self.viewport().update()


class PdfEditPageListWidget(QListWidget):
    file_dropped = Signal(str)
    preview_page_requested = Signal(str, int, int, int)

    PAGE_SIZE = QSize(170, 220)
    TILE_SIZE = QSize(190, 268)
    GRID_SIZE = QSize(212, 292)

    def __init__(self, parent=None):
        super().__init__(parent)
        self._pdf_path = ""
        self.setAcceptDrops(True)
        self.setViewMode(QListView.IconMode)
        self.setResizeMode(QListView.Adjust)
        self.setMovement(QListView.Static)
        self.setWrapping(True)
        self.setIconSize(self.TILE_SIZE)
        self.setGridSize(self.GRID_SIZE)
        self.setSpacing(18)
        self.setWordWrap(True)
        self.setSelectionMode(QListWidget.ExtendedSelection)
        self.setItemDelegate(NoNativeSelectionDelegate(self))
        self.setStyleSheet(
            """
            QListWidget {
                background:#eeeeee;
                border:1px solid #dfe6e9;
                padding:18px;
                font-size:13px;
            }
            QListWidget::item {
                background:transparent;
                border:none;
                color:#2d3436;
            }
            QListWidget::item:selected,
            QListWidget::item:selected:active,
            QListWidget::item:selected:!active,
            QListWidget::item:hover,
            QListWidget::item:focus {
                background:transparent;
                border:none;
                outline:none;
            }
            """
        )
        self.itemDoubleClicked.connect(self._preview_double_clicked_page)

    def load_pdf(self, path):
        self._pdf_path = str(path)
        self.clear()
        page_count = PdfMergeListWidget.pdf_page_count(path)
        for page_index in range(page_count):
            item = QListWidgetItem("")
            item.setData(Qt.UserRole, page_index)
            item.setData(Qt.UserRole + 1, 0)
            item.setTextAlignment(Qt.AlignHCenter)
            item.setSizeHint(self.GRID_SIZE)
            self.addItem(item)
        self.refresh_all_tiles()

    def page_specs(self):
        specs = []
        for row in range(self.count()):
            item = self.item(row)
            specs.append(
                {
                    "page_index": item.data(Qt.UserRole),
                    "rotation": item.data(Qt.UserRole + 1) or 0,
                }
            )
        return specs

    def remove_selected_pages(self):
        rows = sorted((self.row(item) for item in self.selectedItems()), reverse=True)
        if not rows:
            return 0
        for row in rows:
            self.takeItem(row)
        self.refresh_all_tiles()
        return len(rows)

    def rotate_selected_pages(self, delta):
        selected = self.selectedItems()
        if not selected:
            return 0
        for item in selected:
            item.setData(Qt.UserRole + 1, ((item.data(Qt.UserRole + 1) or 0) + delta) % 360)
        self.refresh_all_tiles()
        return len(selected)

    def move_current_page(self, delta):
        row = self.currentRow()
        if row < 0:
            return False
        new_row = row + delta
        if new_row < 0 or new_row >= self.count():
            return False
        item = self.takeItem(row)
        self.insertItem(new_row, item)
        self.setCurrentRow(new_row)
        self.refresh_all_tiles()
        return True

    def preview_current_page(self):
        item = self.currentItem()
        if item is None or not self._pdf_path:
            return False
        self.preview_page_requested.emit(
            self._pdf_path,
            item.data(Qt.UserRole),
            item.data(Qt.UserRole + 1) or 0,
            self.row(item),
        )
        return True

    def clear(self):
        super().clear()
        self.viewport().update()

    def paintEvent(self, event):
        super().paintEvent(event)
        if self.count():
            self._paint_selected_frames()
            return
        painter = QPainter(self.viewport())
        painter.setPen(QColor("#8a98a8"))
        painter.drawText(self.viewport().rect(), Qt.AlignCenter, "拖拽或选择一个 PDF 后，在这里编辑页面")
        painter.end()

    def dragEnterEvent(self, event):
        if self._event_first_pdf(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._event_first_pdf(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._event_first_pdf(event)
        if not path:
            event.ignore()
            return
        self.file_dropped.emit(path)
        event.acceptProposedAction()

    def refresh_all_tiles(self):
        for row in range(self.count()):
            self._refresh_item(self.item(row), row)
        self.viewport().update()

    def _refresh_item(self, item, row):
        page_index = item.data(Qt.UserRole)
        rotation = item.data(Qt.UserRole + 1) or 0
        item.setIcon(QIcon(self._render_page_tile(page_index, row, rotation)))
        item.setToolTip(
            f"当前第 {row + 1} 页，原第 {page_index + 1} 页"
            + (f"，旋转 {rotation} 度" if rotation else "")
        )

    def _render_page_tile(self, page_index, display_index, rotation):
        pixmap = QPixmap(self.TILE_SIZE)
        pixmap.fill(QColor("#eeeeee"))

        page_pixmap = PdfMergeListWidget.render_pdf_thumbnail(self._pdf_path, self.PAGE_SIZE, page_index)
        if rotation:
            page_pixmap = page_pixmap.transformed(QTransform().rotate(rotation), Qt.SmoothTransformation)
            page_pixmap = page_pixmap.scaled(self.PAGE_SIZE, Qt.KeepAspectRatio, Qt.SmoothTransformation)

        painter = QPainter(pixmap)
        painter.setRenderHint(QPainter.Antialiasing)
        x = (self.TILE_SIZE.width() - page_pixmap.width()) // 2
        painter.drawPixmap(x, 0, page_pixmap)
        painter.setPen(QColor("#2d3436"))
        label = f"{display_index + 1} / 原 {page_index + 1}"
        if rotation:
            label += f"\n旋转 {rotation} 度"
        painter.drawText(
            0,
            self.PAGE_SIZE.height() + 8,
            self.TILE_SIZE.width(),
            self.TILE_SIZE.height() - self.PAGE_SIZE.height() - 8,
            Qt.AlignHCenter | Qt.AlignTop,
            label,
        )
        painter.end()
        return pixmap

    def _paint_selected_frames(self):
        painter = QPainter(self.viewport())
        painter.setRenderHint(QPainter.Antialiasing)
        painter.setPen(QColor("#0984e3"))
        painter.setBrush(QColor(219, 234, 254, 90))
        for item in self.selectedItems():
            rect = self.visualItemRect(item)
            if not rect.isValid() or rect.bottom() < 0 or rect.top() > self.viewport().height():
                continue
            frame_width = min(self.TILE_SIZE.width() + 8, rect.width() - 6)
            frame_height = min(self.TILE_SIZE.height() + 8, rect.height() - 6)
            frame_left = rect.left() + (rect.width() - frame_width) // 2
            frame = QRect(frame_left, rect.top() + 3, frame_width, frame_height)
            painter.drawRoundedRect(frame, 4, 4)
        painter.end()

    def _preview_double_clicked_page(self, item):
        self.setCurrentItem(item)
        self.preview_current_page()

    @staticmethod
    def _event_first_pdf(event):
        mime = event.mimeData()
        if not mime.hasUrls():
            return ""
        for url in mime.urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(".pdf") and Path(path).is_file():
                return path
        return ""


class EditablePdfPageWidget(QWidget):
    def __init__(self, parent=None):
        super().__init__(parent)
        self._pixmap = QPixmap()
        self._pdf_size = (1.0, 1.0)
        self._display_size = (1.0, 1.0)
        self._scale = 1.0
        self._rotation = 0
        self._mode = "text"
        self._text = ""
        self._font_size = 14
        self._edits = []
        self._drag_start = None
        self._drag_current = None
        self.setMouseTracking(True)
        self.setMinimumSize(640, 480)

    def load_page(self, path, page_index, rotation=0):
        fitz = _import_fitz()
        self._rotation = rotation % 360
        with fitz.open(str(path)) as doc:
            page = doc.load_page(page_index)
            rect = page.rect
            max_width = 920
            base_scale = min(max_width / max(rect.width, 1), 2.0)
            base_scale = max(base_scale, 1.0)
            rendered = page.get_pixmap(matrix=fitz.Matrix(base_scale, base_scale), alpha=False)
            fmt = QImage.Format_RGB888 if rendered.n < 4 else QImage.Format_RGBA8888
            image = QImage(rendered.samples, rendered.width, rendered.height, rendered.stride, fmt).copy()
            pixmap = QPixmap.fromImage(image)

            self._pdf_size = (float(rect.width), float(rect.height))
            if self._rotation:
                pixmap = pixmap.transformed(QTransform().rotate(self._rotation), Qt.SmoothTransformation)

        self._pixmap = pixmap
        if self._rotation in (90, 270):
            self._display_size = (self._pdf_size[1], self._pdf_size[0])
        else:
            self._display_size = self._pdf_size
        self._scale = self._pixmap.width() / max(self._display_size[0], 1)
        self.setMinimumSize(self._pixmap.size())
        self.resize(self._pixmap.size())
        self._edits = []
        self._drag_start = None
        self._drag_current = None
        self.update()

    def set_mode(self, mode):
        self._mode = mode

    def set_text(self, text):
        self._text = text

    def set_font_size(self, font_size):
        self._font_size = font_size

    def clear_edits(self):
        self._edits = []
        self._drag_start = None
        self._drag_current = None
        self.update()

    def content_edits(self):
        edits = []
        for edit in self._edits:
            if edit["type"] == "text":
                point = self._map_display_point_to_pdf(edit["x"], edit["y"])
                edits.append(
                    {
                        "type": "text",
                        "x": point[0],
                        "y": point[1],
                        "text": edit["text"],
                        "font_size": edit["font_size"],
                    }
                )
            elif edit["type"] == "whiteout":
                x0, y0, x1, y1 = edit["rect"]
                points = [
                    self._map_display_point_to_pdf(x0, y0),
                    self._map_display_point_to_pdf(x1, y0),
                    self._map_display_point_to_pdf(x1, y1),
                    self._map_display_point_to_pdf(x0, y1),
                ]
                xs = [p[0] for p in points]
                ys = [p[1] for p in points]
                edits.append({"type": "whiteout", "rect": [min(xs), min(ys), max(xs), max(ys)]})
        return edits

    def paintEvent(self, event):
        painter = QPainter(self)
        painter.fillRect(self.rect(), QColor("#f8fafc"))
        if self._pixmap.isNull():
            painter.setPen(QColor("#8a98a8"))
            painter.drawText(self.rect(), Qt.AlignCenter, "请先载入 PDF 页面")
            painter.end()
            return

        painter.drawPixmap(0, 0, self._pixmap)
        for edit in self._edits:
            self._paint_edit(painter, edit)
        if self._drag_start and self._drag_current:
            self._paint_whiteout_rect(painter, self._normalized_display_rect(self._drag_start, self._drag_current), True)
        painter.end()

    def mousePressEvent(self, event):
        if self._pixmap.isNull() or not self._inside_pixmap(event.position().toPoint()):
            return
        pos = event.position().toPoint()
        if self._mode == "whiteout":
            self._drag_start = pos
            self._drag_current = pos
        else:
            text = self._text.strip()
            if not text:
                return
            x, y = self._pixel_to_display(pos.x(), pos.y())
            self._edits.append({"type": "text", "x": x, "y": y, "text": text, "font_size": self._font_size})
            self.update()

    def mouseMoveEvent(self, event):
        if self._drag_start:
            pos = event.position().toPoint()
            x = max(0, min(pos.x(), self._pixmap.width()))
            y = max(0, min(pos.y(), self._pixmap.height()))
            self._drag_current = type(pos)(x, y)
            self.update()

    def mouseReleaseEvent(self, event):
        if not self._drag_start or not self._drag_current:
            return
        rect = self._normalized_display_rect(self._drag_start, self._drag_current)
        self._drag_start = None
        self._drag_current = None
        if abs(rect[2] - rect[0]) >= 3 and abs(rect[3] - rect[1]) >= 3:
            self._edits.append({"type": "whiteout", "rect": rect})
        self.update()

    def _paint_edit(self, painter, edit):
        if edit["type"] == "whiteout":
            self._paint_whiteout_rect(painter, edit["rect"], False)
        elif edit["type"] == "text":
            painter.setPen(QColor("#111827"))
            font = QFont()
            font.setPointSizeF(max(6, edit["font_size"] * self._scale))
            painter.setFont(font)
            x, y = self._display_to_pixel(edit["x"], edit["y"])
            painter.drawText(int(x), int(y), edit["text"])

    def _paint_whiteout_rect(self, painter, rect, preview):
        x0, y0 = self._display_to_pixel(rect[0], rect[1])
        x1, y1 = self._display_to_pixel(rect[2], rect[3])
        painter.setPen(QColor("#0984e3" if preview else "#d0d7de"))
        painter.setBrush(QColor(255, 255, 255, 210 if preview else 255))
        painter.drawRect(int(x0), int(y0), int(x1 - x0), int(y1 - y0))

    def _inside_pixmap(self, pos):
        return 0 <= pos.x() <= self._pixmap.width() and 0 <= pos.y() <= self._pixmap.height()

    def _pixel_to_display(self, x, y):
        return x / self._scale, y / self._scale

    def _display_to_pixel(self, x, y):
        return x * self._scale, y * self._scale

    def _normalized_display_rect(self, start, end):
        x0, y0 = self._pixel_to_display(start.x(), start.y())
        x1, y1 = self._pixel_to_display(end.x(), end.y())
        return min(x0, x1), min(y0, y1), max(x0, x1), max(y0, y1)

    def _map_display_point_to_pdf(self, x, y):
        width, height = self._pdf_size
        rotation = self._rotation % 360
        if rotation == 90:
            return y, height - x
        if rotation == 180:
            return width - x, height - y
        if rotation == 270:
            return width - y, x
        return x, y


class PdfContentEditDialog(QDialog):
    def __init__(self, parent, input_file, page_specs, page_row, default_output):
        super().__init__(parent)
        self._input_file = str(input_file)
        self._page_specs = [dict(spec) for spec in page_specs]
        self._page_row = page_row
        self._default_output = default_output

        spec = self._page_specs[self._page_row]
        self.setWindowTitle(f"{Path(input_file).name} - 编辑第 {page_row + 1} 页")
        self.resize(1020, 760)

        layout = QVBoxLayout(self)
        title = QLabel(f"{input_file}    当前第 {page_row + 1} 页 / 原第 {spec['page_index'] + 1} 页")
        if spec.get("rotation"):
            title.setText(title.text() + f"    旋转 {spec['rotation']} 度")
        title.setStyleSheet("font-size:13px;color:#2d3436;")
        layout.addWidget(title)

        controls = QHBoxLayout()
        self.text_input = QLineEdit()
        self.text_input.setPlaceholderText("输入要添加到页面的文字")
        self.font_size = QSpinBox()
        self.font_size.setRange(6, 72)
        self.font_size.setValue(14)
        self.text_mode_btn = QPushButton("添加文字")
        self.whiteout_mode_btn = QPushButton("遮盖区域")
        self.clear_btn = QPushButton("清空本次编辑")
        for btn in (self.text_mode_btn, self.whiteout_mode_btn, self.clear_btn):
            btn.setStyleSheet(parent._secondary_btn())
        self.text_mode_btn.setCheckable(True)
        self.whiteout_mode_btn.setCheckable(True)
        self.text_mode_btn.setChecked(True)
        controls.addWidget(QLabel("文字"))
        controls.addWidget(self.text_input, 1)
        controls.addWidget(QLabel("字号"))
        controls.addWidget(self.font_size)
        controls.addWidget(self.text_mode_btn)
        controls.addWidget(self.whiteout_mode_btn)
        controls.addWidget(self.clear_btn)
        layout.addLayout(controls)

        self.canvas = EditablePdfPageWidget()
        self.canvas.load_page(self._input_file, spec["page_index"], spec.get("rotation", 0))
        scroll = QScrollArea()
        scroll.setWidgetResizable(False)
        scroll.setWidget(self.canvas)
        layout.addWidget(scroll, 1)

        save_row = QHBoxLayout()
        save_row.addStretch()
        close_btn = QPushButton("关闭")
        save_btn = QPushButton("另存为")
        close_btn.setStyleSheet(parent._secondary_btn())
        save_btn.setStyleSheet(parent._btn_style("#0984e3"))
        save_row.addWidget(close_btn)
        save_row.addWidget(save_btn)
        layout.addLayout(save_row)

        self.text_input.textChanged.connect(self.canvas.set_text)
        self.font_size.valueChanged.connect(self.canvas.set_font_size)
        self.text_mode_btn.clicked.connect(lambda: self._set_mode("text"))
        self.whiteout_mode_btn.clicked.connect(lambda: self._set_mode("whiteout"))
        self.clear_btn.clicked.connect(self.canvas.clear_edits)
        close_btn.clicked.connect(self.reject)
        save_btn.clicked.connect(self._save_as)
        self.canvas.set_text(self.text_input.text())
        self.canvas.set_font_size(self.font_size.value())

    def _set_mode(self, mode):
        self.text_mode_btn.setChecked(mode == "text")
        self.whiteout_mode_btn.setChecked(mode == "whiteout")
        self.canvas.set_mode(mode)

    def _save_as(self):
        path, _ = QFileDialog.getSaveFileName(self, "另存为 PDF", self._default_output, "PDF Files (*.pdf)")
        if not path:
            return
        if not path.lower().endswith(".pdf"):
            path += ".pdf"
        edits = self.canvas.content_edits()
        content_edits = {self._page_row: edits} if edits else {}
        try:
            edit_pdf(self._input_file, path, self._page_specs, content_edits)
        except Exception as exc:
            QMessageBox.critical(self, "另存失败", str(exc))
            return
        if hasattr(self.parent(), "_append_log"):
            self.parent()._append_log(f"内容编辑另存完成：{path}")
        QMessageBox.information(self, "完成", f"已另存为：{path}")
        self.accept()


class PdfDropLineEdit(QLineEdit):
    file_dropped = Signal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setAcceptDrops(True)
        self.setProperty("dropInput", True)
        self.setPlaceholderText("支持拖拽 PDF 到此处")
        self.setToolTip("可拖拽 PDF 文件到这里")

    def dragEnterEvent(self, event):
        if self._event_first_pdf(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dragMoveEvent(self, event):
        if self._event_first_pdf(event):
            event.acceptProposedAction()
        else:
            event.ignore()

    def dropEvent(self, event):
        path = self._event_first_pdf(event)
        if not path:
            event.ignore()
            return
        self.file_dropped.emit(path)
        event.acceptProposedAction()

    @staticmethod
    def _event_first_pdf(event):
        mime = event.mimeData()
        if not mime.hasUrls():
            return ""
        for url in mime.urls():
            path = url.toLocalFile()
            if path and path.lower().endswith(".pdf") and Path(path).is_file():
                return path
        return ""


class PDFToolBox(QWidget):
    def __init__(self, lang="zh"):
        super().__init__()
        self.lang = lang
        self._thread = None
        self._worker = None

        title = "PDF Tools" if self.lang == "en" else "PDF 工具集"
        self.setWindowTitle(title)
        self.resize(1280, 860)
        self.setStyleSheet("""
            PDFToolBox { background:#f5f6fa; }
            QWidget#pdfToolPage { background:#f5f6fa; }
            QWidget#pdfToolSection {
                background:white;
                border:1px solid #dfe6e9;
                border-radius:8px;
            }
            QGroupBox { font-weight:bold; color:#2d3436; border:none; margin-top:10px; padding:12px 0 4px 0; }
            QGroupBox::title { padding:0 0 6px 0; border-bottom:2px solid #0984e3; }
            QLineEdit { border:1px solid #dfe6e9; border-radius:4px; padding:7px 8px; background:white; font-size:13px; }
            QLineEdit[dropInput="true"] { border:1px dashed #9bb7d4; background:#fbfdff; }
            QListWidget, QTextEdit { border:1px solid #dfe6e9; border-radius:4px; background:white; font-size:13px; }
            QListWidget { padding:6px; }
            QSpinBox {
                border:1px solid #dfe6e9;
                border-radius:4px;
                padding:3px 26px 3px 8px;
                background:white;
                min-width:82px;
                min-height:30px;
                font-size:13px;
            }
            QSpinBox::up-button {
                subcontrol-origin:border;
                subcontrol-position:top right;
                width:24px;
                height:16px;
                border-left:1px solid #dfe6e9;
                border-bottom:1px solid #edf2f5;
                border-top-right-radius:4px;
                background:#f8fafc;
            }
            QSpinBox::down-button {
                subcontrol-origin:border;
                subcontrol-position:bottom right;
                width:24px;
                height:16px;
                border-left:1px solid #dfe6e9;
                border-bottom-right-radius:4px;
                background:#f8fafc;
            }
            QSpinBox::up-button:hover, QSpinBox::down-button:hover { background:#edf5ff; }
        """)

        root = QVBoxLayout(self)
        root.setContentsMargins(20, 16, 20, 16)
        root.setSpacing(10)

        title = QLabel("PDF 工具集")
        title.setStyleSheet("font-size:18px;font-weight:bold;color:#2d3436;")
        root.addWidget(title)

        self.tools_page = QWidget()
        self.tools_page.setObjectName("pdfToolPage")
        self.tools_layout = QHBoxLayout(self.tools_page)
        self.tools_layout.setContentsMargins(0, 0, 0, 0)
        self.tools_layout.setSpacing(14)
        self.left_tools_layout = QVBoxLayout()
        self.left_tools_layout.setSpacing(14)
        self.right_tools_layout = QVBoxLayout()
        self.right_tools_layout.setSpacing(14)
        self.tools_layout.addLayout(self.left_tools_layout, 1)
        self.tools_layout.addLayout(self.right_tools_layout, 1)
        root.addWidget(self.tools_page, 1)

        self._build_merge_tab()
        self._build_nup_tab()
        self._build_split_tab()
        self._build_edit_tab()

        log_group = QGroupBox("处理日志")
        log_layout = QVBoxLayout(log_group)
        self.log_box = QTextEdit()
        self.log_box.setReadOnly(True)
        self.log_box.setMinimumHeight(130)
        log_layout.addWidget(self.log_box)
        root.addWidget(log_group)

    def _btn_style(self, color="#0984e3"):
        hover = {
            "#0984e3": "#0873c4",
            "#27ae60": "#219a52",
            "#636e72": "#535c69",
            "#d63031": "#c0392b",
        }.get(color, color)
        return (
            f"QPushButton{{background:{color};color:white;padding:8px 20px;"
            "border:none;border-radius:4px;font-size:13px;}}"
            f"QPushButton:hover{{background:{hover};}}"
            "QPushButton:disabled{background:#b2bec3;color:white;}"
        )

    def _secondary_btn(self):
        return (
            "QPushButton{background:white;color:#2d3436;padding:7px 16px;"
            "border:1px solid #d0d0d0;border-radius:4px;font-size:13px;}"
            "QPushButton:hover{background:#f0f2f5;}"
        )

    def _tr(self, zh: str, en: str) -> str:
        """根据当前语言返回对应文本"""
        return en if self.lang == "en" else zh

    def _path_row(self, label, line_edit, browse_func):
        row = QHBoxLayout()
        row.addWidget(QLabel(label))
        row.addWidget(line_edit, 1)
        btn = QPushButton("浏览")
        btn.setStyleSheet(self._secondary_btn())
        btn.clicked.connect(browse_func)
        row.addWidget(btn)
        return row

    def _setup_spinbox(self, spinbox):
        spinbox.setButtonSymbols(QSpinBox.UpDownArrows)
        spinbox.setFixedSize(92, 34)
        spinbox.setKeyboardTracking(False)

    def _section_title(self, text):
        title = QLabel(text)
        title.setStyleSheet("font-size:16px;font-weight:bold;color:#1f2933;")
        return title

    def _build_merge_tab(self):
        tab = QWidget()
        tab.setObjectName("pdfToolSection")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("PDF 合并"))

        file_group = QGroupBox("输入 PDF 文件")
        file_layout = QVBoxLayout(file_group)
        self.merge_list = PdfMergeListWidget()
        self.merge_list.setSelectionMode(QListWidget.ExtendedSelection)
        self.merge_list.setToolTip("可拖拽多个 PDF 文件到这里")
        file_layout.addWidget(self.merge_list)

        btn_row = QHBoxLayout()
        add_btn = QPushButton("添加 PDF")
        remove_btn = QPushButton("移除选中")
        clear_btn = QPushButton("清空")
        up_btn = QPushButton("上移")
        down_btn = QPushButton("下移")
        self.merge_browse_btn = QPushButton("浏览")
        self.merge_list_btn = QPushButton("列表")
        for btn in (self.merge_browse_btn, self.merge_list_btn):
            btn.setCheckable(True)
            btn.setStyleSheet(self._secondary_btn())
        for btn in (add_btn, remove_btn, clear_btn, up_btn, down_btn):
            btn.setStyleSheet(self._secondary_btn())
            btn_row.addWidget(btn)
        btn_row.addStretch()
        btn_row.addWidget(QLabel("显示模式"))
        btn_row.addWidget(self.merge_browse_btn)
        btn_row.addWidget(self.merge_list_btn)
        file_layout.addLayout(btn_row)
        layout.addWidget(file_group, 1)

        self.merge_output = QLineEdit()
        layout.addLayout(self._path_row("输出文件", self.merge_output, self._choose_merge_output))

        run = QPushButton("Start Merge" if self.lang == "en" else self._tr("开始合并", "Start Merge"))
        run.setStyleSheet(self._btn_style("#0984e3"))
        layout.addWidget(run, alignment=Qt.AlignRight)

        add_btn.clicked.connect(self._add_merge_files)
        remove_btn.clicked.connect(self.merge_list.remove_selected_items)
        clear_btn.clicked.connect(self.merge_list.clear)
        up_btn.clicked.connect(lambda: self._move_selected(self.merge_list, -1))
        down_btn.clicked.connect(lambda: self._move_selected(self.merge_list, 1))
        self.merge_list.files_dropped.connect(self._handle_merge_files)
        self.merge_list.preview_requested.connect(self._preview_merge_pdf)
        self.merge_list.expand_requested.connect(self._expand_merge_pdf)
        self.merge_browse_btn.clicked.connect(lambda: self._set_merge_browse_mode(True))
        self.merge_list_btn.clicked.connect(lambda: self._set_merge_browse_mode(False))
        self._set_merge_browse_mode(True)
        run.clicked.connect(self._run_merge)
        self.left_tools_layout.addWidget(tab, 5)

    def _build_split_tab(self):
        tab = QWidget()
        tab.setObjectName("pdfToolSection")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("PDF 拆分"))

        self.split_input = PdfDropLineEdit()
        self.split_output_dir = QLineEdit()
        self.split_pages = QSpinBox()
        self.split_pages.setRange(1, 9999)
        self.split_pages.setValue(1)
        self._setup_spinbox(self.split_pages)
        self.split_prefix = QLineEdit()

        layout.addLayout(self._path_row("输入文件", self.split_input, self._choose_split_input))
        layout.addLayout(self._path_row("输出目录", self.split_output_dir, self._choose_split_dir))

        opt = QHBoxLayout()
        opt.addWidget(QLabel("每个 PDF 页数"))
        opt.addWidget(self.split_pages)
        opt.addSpacing(20)
        opt.addWidget(QLabel("文件名前缀"))
        opt.addWidget(self.split_prefix, 1)
        layout.addLayout(opt)
        layout.addStretch(1)

        run = QPushButton("Start Split" if self.lang == "en" else self._tr("开始拆分", "Start Split"))
        run.setStyleSheet(self._btn_style("#27ae60"))
        layout.addWidget(run, alignment=Qt.AlignRight)

        self.split_input.file_dropped.connect(self._set_split_input)
        run.clicked.connect(self._run_split)
        self.left_tools_layout.addWidget(tab, 3)

    def _build_nup_tab(self):
        tab = QWidget()
        tab.setObjectName("pdfToolSection")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("A4 拼版"))

        self.nup_input = PdfDropLineEdit()
        self.nup_output = QLineEdit()
        self.nup_pages = QSpinBox()
        self.nup_pages.setRange(1, 64)
        self.nup_pages.setValue(4)
        self.nup_rows = QSpinBox()
        self.nup_rows.setRange(1, 64)
        self.nup_rows.setValue(2)
        self.nup_margin = QSpinBox()
        self.nup_margin.setRange(0, 50)
        self.nup_margin.setValue(5)
        for spin in (self.nup_pages, self.nup_rows, self.nup_margin):
            self._setup_spinbox(spin)
        self.nup_preview = QLabel()
        self.nup_preview.setStyleSheet("color:#636e72;font-size:13px;")

        layout.addLayout(self._path_row("输入文件", self.nup_input, self._choose_nup_input))
        layout.addLayout(self._path_row("输出文件", self.nup_output, self._choose_nup_output))

        opt = QHBoxLayout()
        opt.addWidget(QLabel("每张 A4 页数"))
        opt.addWidget(self.nup_pages)
        opt.addSpacing(20)
        opt.addWidget(QLabel("行数"))
        opt.addWidget(self.nup_rows)
        opt.addSpacing(20)
        opt.addWidget(QLabel("边距"))
        opt.addWidget(self.nup_margin)
        opt.addWidget(QLabel("pt"))
        opt.addStretch()
        layout.addLayout(opt)
        layout.addWidget(self.nup_preview)
        layout.addStretch(1)

        run = QPushButton("Start Layout" if self.lang == "en" else self._tr("开始拼版", "Start Imposition"))
        run.setStyleSheet(self._btn_style("#0984e3"))
        layout.addWidget(run, alignment=Qt.AlignRight)

        self.nup_pages.valueChanged.connect(self._refresh_nup_preview)
        self.nup_rows.valueChanged.connect(self._refresh_nup_preview)
        self.nup_input.file_dropped.connect(self._set_nup_input)
        self._refresh_nup_preview()
        run.clicked.connect(self._run_nup)
        self.right_tools_layout.addWidget(tab, 4)

    def _build_edit_tab(self):
        tab = QWidget()
        tab.setObjectName("pdfToolSection")
        layout = QVBoxLayout(tab)
        layout.setContentsMargins(20, 16, 20, 18)
        layout.setSpacing(12)
        layout.addWidget(self._section_title("编辑 PDF"))

        self.edit_input = PdfDropLineEdit()
        self.edit_output = QLineEdit()
        self.edit_page_list = PdfEditPageListWidget()

        layout.addLayout(self._path_row("输入文件", self.edit_input, self._choose_edit_input))
        layout.addLayout(self._path_row("输出文件", self.edit_output, self._choose_edit_output))

        page_group = QGroupBox("页面编辑")
        page_layout = QVBoxLayout(page_group)
        page_layout.addWidget(self.edit_page_list)

        btn_row = QHBoxLayout()
        preview_btn = QPushButton("放大预览")
        remove_btn = QPushButton("删除选中")
        rotate_left_btn = QPushButton("左旋 90 度")
        rotate_right_btn = QPushButton("右旋 90 度")
        up_btn = QPushButton("上移")
        down_btn = QPushButton("下移")
        reset_btn = QPushButton("重新载入")
        for btn in (
            preview_btn,
            remove_btn,
            rotate_left_btn,
            rotate_right_btn,
            up_btn,
            down_btn,
            reset_btn,
        ):
            btn.setStyleSheet(self._secondary_btn())
            btn_row.addWidget(btn)
        btn_row.addStretch()
        page_layout.addLayout(btn_row)
        layout.addWidget(page_group, 1)

        run = QPushButton("保存编辑")
        run.setStyleSheet(self._btn_style("#0984e3"))
        layout.addWidget(run, alignment=Qt.AlignRight)

        self.edit_input.file_dropped.connect(self._set_edit_input)
        self.edit_page_list.file_dropped.connect(self._set_edit_input)
        self.edit_page_list.preview_page_requested.connect(self._preview_edit_pdf)
        preview_btn.clicked.connect(self._preview_edit_current)
        remove_btn.clicked.connect(self._remove_edit_pages)
        rotate_left_btn.clicked.connect(lambda: self._rotate_edit_pages(-90))
        rotate_right_btn.clicked.connect(lambda: self._rotate_edit_pages(90))
        up_btn.clicked.connect(lambda: self._move_edit_page(-1))
        down_btn.clicked.connect(lambda: self._move_edit_page(1))
        reset_btn.clicked.connect(self._reload_edit_input)
        run.clicked.connect(self._run_edit)
        self.right_tools_layout.addWidget(tab, 5)

    def _append_log(self, msg):
        self.log_box.append(msg)

    def _set_merge_browse_mode(self, enabled):
        self.merge_list.set_browse_mode(enabled)
        self.merge_browse_btn.setChecked(enabled)
        self.merge_list_btn.setChecked(not enabled)

    def _preview_merge_pdf(self, path, page_index=0):
        dialog = QDialog(self)
        suffix = f" - 第 {page_index + 1} 页" if page_index else ""
        dialog.setWindowTitle(Path(path).name + suffix)
        dialog.resize(860, 720)

        layout = QVBoxLayout(dialog)
        title = QLabel(f"{path}    第 {page_index + 1} 页")
        title.setStyleSheet("font-size:13px;color:#2d3436;")
        layout.addWidget(title)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        preview = QLabel()
        preview.setAlignment(Qt.AlignCenter)
        preview.setStyleSheet("background:#f8fafc;border:1px solid #dfe6e9;")
        preview.setPixmap(PdfMergeListWidget.render_pdf_thumbnail(path, QSize(760, 980), page_index))
        scroll.setWidget(preview)
        layout.addWidget(scroll, 1)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(self._secondary_btn())
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        dialog.exec()

    def _expand_merge_pdf(self, path):
        dialog = QDialog(self)
        dialog.setWindowTitle(f"{Path(path).name} - 展开预览")
        dialog.resize(980, 720)

        layout = QVBoxLayout(dialog)
        title = QLabel(str(path))
        title.setStyleSheet("font-size:13px;color:#2d3436;")
        layout.addWidget(title)

        page_list = PdfPagePreviewListWidget()
        page_list.load_pdf(path)
        page_list.preview_page_requested.connect(self._preview_merge_pdf)
        layout.addWidget(page_list, 1)

        close_btn = QPushButton("关闭")
        close_btn.setStyleSheet(self._secondary_btn())
        close_btn.clicked.connect(dialog.accept)
        layout.addWidget(close_btn, alignment=Qt.AlignRight)
        dialog.exec()

    def _preview_edit_pdf(self, path, page_index, rotation=0, page_row=0):
        default_output = self.edit_output.text().strip()
        if not default_output:
            src = Path(path)
            default_output = str(src.with_name(src.stem + "_内容编辑.pdf"))
        dialog = PdfContentEditDialog(
            self,
            path,
            self.edit_page_list.page_specs(),
            page_row,
            default_output,
        )
        dialog.exec()

    def _add_merge_files(self):
        files, _ = QFileDialog.getOpenFileNames(self, "选择 PDF 文件", "", "PDF Files (*.pdf)")
        self._handle_merge_files(files)

    def _handle_merge_files(self, files):
        files = [str(Path(file)) for file in files if str(file).strip() and str(file).lower().endswith(".pdf")]
        if not files:
            return
        added = 0
        for file in files:
            if not self.merge_list.contains_path(file):
                self.merge_list.add_pdf(file)
                added += 1
        if len(files) > 1:
            self._set_merge_browse_mode(True)
        if not self.merge_output.text().strip():
            first = Path(files[0])
            self.merge_output.setText(str(first.with_name(first.stem + "_合并.pdf")))
        if added:
            self._append_log(f"已添加 {added} 个 PDF 文件")

    def _choose_merge_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "选择输出文件", self.merge_output.text(), "PDF Files (*.pdf)")
        if path:
            self.merge_output.setText(self._ensure_pdf_suffix(path))

    def _choose_split_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 文件", "", "PDF Files (*.pdf)")
        if path:
            self._set_split_input(path)

    def _set_split_input(self, path):
        src = Path(path)
        self.split_input.setText(str(src))
        if not self.split_output_dir.text().strip():
            self.split_output_dir.setText(str(src.with_name(src.stem + "_拆分")))
        if not self.split_prefix.text().strip():
            self.split_prefix.setText(src.stem)
        self._append_log(f"已选择拆分输入：{src}")

    def _choose_split_dir(self):
        path = QFileDialog.getExistingDirectory(self, "选择输出目录", self.split_output_dir.text())
        if path:
            self.split_output_dir.setText(path)

    def _choose_nup_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 文件", "", "PDF Files (*.pdf)")
        if path:
            self._set_nup_input(path)

    def _set_nup_input(self, path):
        src = Path(path)
        self.nup_input.setText(str(src))
        if not self.nup_output.text().strip():
            pages = self.nup_pages.value()
            rows = self.nup_rows.value()
            self.nup_output.setText(str(src.with_name(f"{src.stem}_A4横向{pages}合1_{rows}行.pdf")))
        self._append_log(f"已选择拼版输入：{src}")

    def _choose_nup_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "选择输出文件", self.nup_output.text(), "PDF Files (*.pdf)")
        if path:
            self.nup_output.setText(self._ensure_pdf_suffix(path))

    def _choose_edit_input(self):
        path, _ = QFileDialog.getOpenFileName(self, "选择 PDF 文件", "", "PDF Files (*.pdf)")
        if path:
            self._set_edit_input(path)

    def _set_edit_input(self, path):
        src = Path(path)
        self.edit_input.setText(str(src))
        if not self.edit_output.text().strip():
            self.edit_output.setText(str(src.with_name(src.stem + "_编辑.pdf")))
        self.edit_page_list.load_pdf(src)
        self._append_log(f"已选择编辑输入：{src}，共 {self.edit_page_list.count()} 页")

    def _choose_edit_output(self):
        path, _ = QFileDialog.getSaveFileName(self, "选择输出文件", self.edit_output.text(), "PDF Files (*.pdf)")
        if path:
            self.edit_output.setText(self._ensure_pdf_suffix(path))

    def _reload_edit_input(self):
        src = self.edit_input.text().strip()
        if not src:
            QMessageBox.warning(self, "提示", "请先选择输入 PDF。")
            return
        self.edit_page_list.load_pdf(src)
        self._append_log(f"已重新载入编辑输入：{src}")

    def _preview_edit_current(self):
        if not self.edit_page_list.preview_current_page():
            QMessageBox.information(self, "提示", "请先选择要预览的页面。")

    def _remove_edit_pages(self):
        selected_count = len(self.edit_page_list.selectedItems())
        if selected_count < 1:
            QMessageBox.information(self, "提示", "请先选择要删除的页面。")
            return
        if selected_count >= self.edit_page_list.count():
            QMessageBox.warning(self, "提示", "至少需要保留一页。")
            return
        removed = self.edit_page_list.remove_selected_pages()
        if removed:
            self._append_log(f"编辑PDF：已删除 {removed} 页")

    def _rotate_edit_pages(self, delta):
        changed = self.edit_page_list.rotate_selected_pages(delta)
        if not changed:
            QMessageBox.information(self, "提示", "请先选择要旋转的页面。")
            return
        direction = "右旋" if delta > 0 else "左旋"
        self._append_log(f"编辑PDF：已{direction} {changed} 页")

    def _move_edit_page(self, delta):
        if not self.edit_page_list.move_current_page(delta):
            QMessageBox.information(self, "提示", "请选择页面，且确认页面还可以继续移动。")

    def _run_merge(self):
        files = self.merge_list.file_paths()
        output = self.merge_output.text().strip()
        if not files or not output:
            QMessageBox.warning(self, "提示", "请选择输入 PDF 并设置输出文件。")
            return
        self._start_worker("开始合并 PDF...", merge_pdfs, files, output)

    def _run_split(self):
        src = self.split_input.text().strip()
        out_dir = self.split_output_dir.text().strip()
        if not src or not out_dir:
            QMessageBox.warning(self, "提示", "请选择输入 PDF 和输出目录。")
            return
        self._start_worker(
            "开始拆分 PDF...",
            split_pdf,
            src,
            out_dir,
            self.split_pages.value(),
            self.split_prefix.text().strip() or None,
        )

    def _run_nup(self):
        src = self.nup_input.text().strip()
        output = self.nup_output.text().strip()
        pages = self.nup_pages.value()
        rows = self.nup_rows.value()
        if rows > pages:
            QMessageBox.warning(self, "提示", "行数不能大于每张 A4 页数。")
            return
        if not src or not output:
            QMessageBox.warning(self, "提示", "请选择输入 PDF 并设置输出文件。")
            return
        self._start_worker(
            "开始 A4 拼版...",
            nup_pdf_to_a4,
            src,
            output,
            pages,
            rows,
            True,
            float(self.nup_margin.value()),
        )

    def _run_edit(self):
        src = self.edit_input.text().strip()
        output = self.edit_output.text().strip()
        page_specs = self.edit_page_list.page_specs()
        if not src or not output:
            QMessageBox.warning(self, "提示", "请选择输入 PDF 并设置输出文件。")
            return
        if not page_specs:
            QMessageBox.warning(self, "提示", "请先载入 PDF 页面。")
            return
        self._start_worker("开始编辑 PDF...", edit_pdf, src, output, page_specs)

    def _start_worker(self, start_msg, func, *args, **kwargs):
        if self._thread and self._thread.isRunning():
            QMessageBox.information(self, "提示", "当前已有任务正在执行，请稍候。")
            return
        self._append_log(start_msg)
        self._thread = QThread(self)
        self._worker = PdfWorker(func, *args, **kwargs)
        self._worker.moveToThread(self._thread)
        self._thread.started.connect(self._worker.run)
        self._worker.finished.connect(self._on_worker_finished)
        self._worker.failed.connect(self._on_worker_failed)
        self._worker.finished.connect(self._thread.quit)
        self._worker.failed.connect(self._thread.quit)
        self._worker.finished.connect(self._worker.deleteLater)
        self._worker.failed.connect(self._worker.deleteLater)
        self._thread.finished.connect(self._thread.deleteLater)
        self._thread.finished.connect(self._cleanup_worker)
        self._thread.start()

    def _on_worker_finished(self, result):
        if isinstance(result, list):
            self._append_log(f"处理完成，共生成 {len(result)} 个文件。")
            if result:
                self._append_log(f"输出目录：{result[0].parent}")
        else:
            self._append_log(f"处理完成：{result}")
        QMessageBox.information(self, "完成", "PDF 处理完成。")

    def _on_worker_failed(self, msg):
        self._append_log(f"处理失败：{msg}")
        QMessageBox.critical(self, "处理失败", msg)

    def _cleanup_worker(self):
        self._thread = None
        self._worker = None

    def _refresh_nup_preview(self):
        pages = self.nup_pages.value()
        rows = min(self.nup_rows.value(), pages)
        cols = math.ceil(pages / rows)
        self.nup_preview.setText(
            f"当前参数：每张 A4 横版拼接 {pages} 页，按 {rows} 行 x {cols} 列排列；最后一张自动放置剩余页面。"
        )

    @staticmethod
    def _ensure_pdf_suffix(path):
        return path if path.lower().endswith(".pdf") else path + ".pdf"

    @staticmethod
    def _list_contains(list_widget, text):
        for i in range(list_widget.count()):
            if list_widget.item(i).text() == text:
                return True
        return False

    @staticmethod
    def _remove_selected(list_widget):
        for item in list_widget.selectedItems():
            list_widget.takeItem(list_widget.row(item))

    @staticmethod
    def _move_selected(list_widget, delta):
        row = list_widget.currentRow()
        if row < 0:
            return
        new_row = row + delta
        if new_row < 0 or new_row >= list_widget.count():
            return
        item = list_widget.takeItem(row)
        list_widget.insertItem(new_row, item)
        list_widget.setCurrentRow(new_row)


if __name__ == "__main__":
    app = QApplication(sys.argv)
    w = PDFToolBox()
    w.show()
    sys.exit(app.exec())
