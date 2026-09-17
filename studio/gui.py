from __future__ import annotations

import sys
import threading
import traceback
from datetime import datetime
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal, Slot, Qt
from PySide6.QtWidgets import (
    QApplication, QComboBox, QFileDialog, QGroupBox, QHBoxLayout, QHeaderView,
    QLabel, QLineEdit, QMainWindow, QMessageBox, QPlainTextEdit, QProgressBar,
    QPushButton, QSpinBox, QTabWidget, QTableWidget, QTableWidgetItem,
    QVBoxLayout, QWidget,
)

from studio.backend import FordBackend, StudioError
from ford.ecu_database import load_ecu_database, get_ecu_name


class Worker(QObject):
    finished = Signal()
    failed = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn

    @Slot()
    def run(self):
        try:
            self.fn()
        except Exception as exc:
            self.failed.emit(f"{exc}\n\n{traceback.format_exc()}")
        finally:
            self.finished.emit()


class DropTable(QTableWidget):
    files_dropped = Signal(list)

    def __init__(self, *args):
        super().__init__(*args)
        self.setAcceptDrops(True)
        self.setDragDropMode(QTableWidget.DragDrop)
        self.setSelectionBehavior(QTableWidget.SelectRows)

    def dragEnterEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragEnterEvent(event)

    def dragMoveEvent(self, event):
        if event.mimeData().hasUrls():
            event.acceptProposedAction()
        else:
            super().dragMoveEvent(event)

    def dropEvent(self, event):
        if event.mimeData().hasUrls():
            paths = [u.toLocalFile() for u in event.mimeData().urls() if u.toLocalFile().lower().endswith('.vbf')]
            if paths:
                self.files_dropped.emit(paths)
            event.acceptProposedAction()
        else:
            super().dropEvent(event)


class MainWindow(QMainWindow):
    log_signal = Signal(str)
    progress_signal = Signal(int, int, str)
    info_signal = Signal(dict)
    uds_signal = Signal(bytes, bytes)
    can_signal = Signal(str)

    def __init__(self):
        super().__init__()
        self.setWindowTitle("Ford UDS Studio 2.11 Stable")
        self.resize(1220, 820)
        self.backend = FordBackend(self.log_signal.emit, self.progress_signal.emit)
        self.thread: QThread | None = None
        self.worker: Worker | None = None
        self.can_stop = threading.Event()
        self.log_signal.connect(self.append_log)
        self.progress_signal.connect(self.update_progress)
        self.info_signal.connect(self.show_info)
        self.uds_signal.connect(self.show_uds)
        self.can_signal.connect(self.append_can)
        self._build_ui()
        self.populate_ecu_combo()
        self.refresh_interfaces()

    def _build_ui(self):
        root = QWidget(); self.setCentralWidget(root)
        layout = QVBoxLayout(root)
        connection = QGroupBox("Połączenie")
        row = QHBoxLayout(connection)
        self.interface_combo = QComboBox()
        self.ecu_combo = QComboBox()
        self.ecu_combo.setMinimumWidth(250)
        self.ecu_edit = QLineEdit("0x720")
        self.ecu_edit.setMaximumWidth(95)
        self.refresh_btn = QPushButton("Odśwież")
        self.connect_btn = QPushButton("Połącz")
        self.disconnect_btn = QPushButton("Rozłącz")
        row.addWidget(QLabel("Interfejs:")); row.addWidget(self.interface_combo, 1); row.addWidget(self.refresh_btn)
        row.addWidget(QLabel("Moduł:")); row.addWidget(self.ecu_combo)
        row.addWidget(QLabel("ECU ID:")); row.addWidget(self.ecu_edit)
        row.addWidget(self.connect_btn); row.addWidget(self.disconnect_btn)
        layout.addWidget(connection)
        self.tabs = QTabWidget()
        self.tabs.addTab(self._flash_tab(), "VBF Flasher")
        self.tabs.addTab(self._security_tab(), "Security")
        self.tabs.addTab(self._eeprom_tab(), "EEPROM")
        self.tabs.addTab(self._uds_tab(), "UDS Terminal")
        self.tabs.addTab(self._info_tab(), "ECU Info")
        self.tabs.addTab(self._can_tab(), "CAN Monitor")
        layout.addWidget(self.tabs, 1)
        self.statusBar().showMessage("Gotowy")
        self.refresh_btn.clicked.connect(self.refresh_interfaces)
        self.ecu_combo.currentIndexChanged.connect(self.ecu_selection_changed)
        self.connect_btn.clicked.connect(self.connect_ecu)
        self.disconnect_btn.clicked.connect(self.backend.disconnect)

    def _flash_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); controls=QHBoxLayout()
        add=QPushButton("Dodaj VBF…"); remove=QPushButton("Usuń"); clear=QPushButton("Wyczyść")
        up=QPushButton("▲ Wyżej"); down=QPushButton("▼ Niżej")
        self.unlock_btn=QPushButton("Test unlock"); self.flash_btn=QPushButton("FLASH"); self.cancel_btn=QPushButton("Przerwij"); self.cancel_btn.setEnabled(False)
        for w in (add,remove,clear,up,down): controls.addWidget(w)
        controls.addStretch(); controls.addWidget(self.unlock_btn); controls.addWidget(self.flash_btn); controls.addWidget(self.cancel_btn); layout.addLayout(controls)
        self.vbf_table=DropTable(0,7)
        self.vbf_table.setHorizontalHeaderLabels(["#","Plik","Typ","Part number","ECU","Tryb","Rozmiar danych"])
        self.vbf_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch); self.vbf_table.horizontalHeader().setSectionResizeMode(3,QHeaderView.Stretch)
        layout.addWidget(self.vbf_table,1)
        self.vbf_details=QPlainTextEdit(); self.vbf_details.setReadOnly(True); self.vbf_details.setMaximumHeight(125); layout.addWidget(self.vbf_details)
        self.progress_label=QLabel("Gotowy"); self.progress=QProgressBar(); layout.addWidget(self.progress_label); layout.addWidget(self.progress)
        logrow=QHBoxLayout(); logrow.addWidget(QLabel("Log operacji")); logrow.addStretch(); save=QPushButton("Zapisz log"); clearlog=QPushButton("Wyczyść log"); logrow.addWidget(save); logrow.addWidget(clearlog); layout.addLayout(logrow)
        self.log=QPlainTextEdit(); self.log.setReadOnly(True); self.log.setMaximumBlockCount(20000); layout.addWidget(self.log,1)
        add.clicked.connect(self.add_vbfs); remove.clicked.connect(self.remove_selected); clear.clicked.connect(self.clear_vbfs)
        up.clicked.connect(lambda:self.move_entry(-1)); down.clicked.connect(lambda:self.move_entry(1)); self.vbf_table.files_dropped.connect(self.add_paths)
        self.vbf_table.itemSelectionChanged.connect(self.show_vbf_details)
        self.unlock_btn.clicked.connect(self.unlock_test); self.flash_btn.clicked.connect(self.start_flash); self.cancel_btn.clicked.connect(self.backend.cancel)
        save.clicked.connect(self.save_log); clearlog.clicked.connect(self.log.clear)
        return page

    def _security_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); row=QHBoxLayout()
        self.security_level=QSpinBox(); self.security_level.setRange(1,255); self.security_level.setValue(1); self.security_level.setDisplayIntegerBase(16); self.security_level.setPrefix("0x")
        btn=QPushButton("Wykonaj Security Access"); row.addWidget(QLabel("Poziom seed:")); row.addWidget(self.security_level); row.addWidget(btn); row.addStretch(); layout.addLayout(row)
        self.security_output=QPlainTextEdit(); self.security_output.setReadOnly(True); layout.addWidget(self.security_output)
        btn.clicked.connect(self.unlock_test); return page

    def _eeprom_tab(self):
        page=QWidget(); layout=QVBoxLayout(page)
        warning=QLabel(
            "GM2T EEPROM READ/WRITE. Wymaga SBL o payloadzie 0x35C i call 0x40003600. "
            "Zapis działa bezpośrednio z pliku EEPROM.bin 4096 B i przed kasowaniem tworzy backup."
        )
        warning.setWordWrap(True); layout.addWidget(warning)
        row=QHBoxLayout()
        self.eeprom_profile=QComboBox()
        self.eeprom_profile.addItem("GM2T — verified, magic 0x4A7722", "gm2t")
        self.eeprom_read_btn=QPushButton("Odczytaj EEPROM 0x1000…")
        self.eeprom_write_btn=QPushButton("Kasuj + wgraj EEPROM.bin…")
        row.addWidget(QLabel("Profil Security:")); row.addWidget(self.eeprom_profile,1); row.addWidget(self.eeprom_read_btn); row.addWidget(self.eeprom_write_btn)
        layout.addLayout(row)
        self.eeprom_status=QPlainTextEdit(); self.eeprom_status.setReadOnly(True)
        self.eeprom_status.setPlainText(
            "Profil: GM2T / DS7T-14F094 family\n"
            "Security: ford_3byte, magic 0x4A7722\n"
            "Wymagany SBL: payload 0x35C, call 0x40003600\n"
            "Adres logiczny: 0x02000000\nRozmiar: 0x1000 (4096 B)\n"
            "READ: RequestUpload (0x35) + TransferData (0x36)\n"
            "WRITE: backup, erase FF00, RequestDownload (0x34), TransferData, commit 0304"
        )
        layout.addWidget(self.eeprom_status)
        self.eeprom_read_btn.clicked.connect(self.read_eeprom)
        self.eeprom_write_btn.clicked.connect(self.write_eeprom)
        return page

    def _uds_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); row=QHBoxLayout(); self.uds_input=QLineEdit("22 F1 90"); send=QPushButton("Wyślij")
        row.addWidget(QLabel("UDS HEX:")); row.addWidget(self.uds_input,1); row.addWidget(send); layout.addLayout(row)
        self.uds_output=QPlainTextEdit(); self.uds_output.setReadOnly(True); layout.addWidget(self.uds_output); send.clicked.connect(self.send_uds); return page

    def _info_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); read=QPushButton("Odczytaj informacje ECU")
        self.info_table=QTableWidget(0,2); self.info_table.setHorizontalHeaderLabels(["Pole","Wartość"]); self.info_table.horizontalHeader().setSectionResizeMode(1,QHeaderView.Stretch)
        layout.addWidget(read); layout.addWidget(self.info_table); read.clicked.connect(self.read_info); return page

    def _can_tab(self):
        page=QWidget(); layout=QVBoxLayout(page); row=QHBoxLayout(); start=QPushButton("Start monitor"); stop=QPushButton("Stop"); save=QPushButton("Zapisz log")
        row.addWidget(start); row.addWidget(stop); row.addWidget(save); row.addStretch(); layout.addLayout(row)
        self.can_output=QPlainTextEdit(); self.can_output.setReadOnly(True); self.can_output.setMaximumBlockCount(50000); layout.addWidget(self.can_output)
        start.clicked.connect(self.start_can_monitor); stop.clicked.connect(self.stop_can_monitor); save.clicked.connect(self.save_can_log); return page

    def populate_ecu_combo(self):
        """Build the ECU selector directly from config/ecus.json."""
        self.ecu_combo.blockSignals(True)
        self.ecu_combo.clear()
        preferred = [0x720, 0x727, 0x7D0]
        database = load_ecu_database()
        ordered = [ecu for ecu in preferred if ecu in database]
        ordered += sorted(ecu for ecu in database if ecu not in preferred)
        for ecu_id in ordered:
            name = get_ecu_name(ecu_id)
            self.ecu_combo.addItem(f"{name}  [0x{ecu_id:03X}]", ecu_id)
        self.ecu_combo.addItem("Inny / adres ręczny", None)
        self.ecu_combo.blockSignals(False)
        self.select_ecu(0x720)

    @Slot()
    def ecu_selection_changed(self):
        ecu_id = self.ecu_combo.currentData()
        if ecu_id is not None:
            self.ecu_edit.setText(f"0x{int(ecu_id):03X}")
            self.ecu_edit.setReadOnly(True)
        else:
            self.ecu_edit.setReadOnly(False)
            self.ecu_edit.setFocus()

    def select_ecu(self, ecu_id: int):
        for index in range(self.ecu_combo.count()):
            if self.ecu_combo.itemData(index) == ecu_id:
                self.ecu_combo.setCurrentIndex(index)
                self.ecu_edit.setText(f"0x{ecu_id:03X}")
                self.ecu_edit.setReadOnly(True)
                return
        self.ecu_combo.setCurrentIndex(self.ecu_combo.count() - 1)
        self.ecu_edit.setReadOnly(False)
        self.ecu_edit.setText(f"0x{ecu_id:03X}")

    def selected_interface(self):
        value=self.interface_combo.currentData()
        if value is None: raise StudioError("Nie wybrano interfejsu.")
        return str(value)

    def closeEvent(self, event):
        try:
            self.can_stop.set()
            self.backend.cancel()
            self.backend.disconnect()
        except Exception:
            pass
        event.accept()

    @Slot()
    def refresh_interfaces(self):
        self.interface_combo.clear()
        for label,value in self.backend.detect_interfaces(): self.interface_combo.addItem(label,value)

    def add_vbfs(self):
        paths,_=QFileDialog.getOpenFileNames(self,"Wybierz pliki VBF",str(Path.home()),"VBF (*.vbf);;Wszystkie pliki (*)")
        self.add_paths(paths)

    @Slot(list)
    def add_paths(self, paths):
        if not paths: return
        existing=[str(e.path) for e in self.backend.entries]
        unique=existing+[p for p in paths if str(Path(p).resolve()) not in {str(Path(x).resolve()) for x in existing}]
        try: entries=self.backend.load_files(unique)
        except Exception as exc: QMessageBox.critical(self,"Błąd VBF",str(exc)); return
        self.populate_vbf_table(entries)
        self.select_ecu(entries[0].ecu_id)

    def populate_vbf_table(self, entries):
        self.vbf_table.setRowCount(len(entries))
        for row,e in enumerate(entries):
            total=sum(ds['size'] for ds in e.vbf.data)
            vals=[str(row+1),e.path.name,e.kind,e.part_number,f"0x{e.ecu_id:03X}","JADE" if e.is_jade else "klasyczny",f"{total:,}"]
            for col,val in enumerate(vals): self.vbf_table.setItem(row,col,QTableWidgetItem(val))

    def show_vbf_details(self):
        row=self.vbf_table.currentRow()
        if not (0<=row<len(self.backend.entries)): self.vbf_details.clear(); return
        e=self.backend.entries[row]; erase=e.vbf.header.get('erase','brak'); segments='\n'.join(f"  0x{d['addr']:08X} / 0x{d['size']:X}" for d in e.vbf.data)
        self.vbf_details.setPlainText(f"{e.part_number} | {e.kind} | ECU 0x{e.ecu_id:03X} | {'JADE' if e.is_jade else 'klasyczny'}\nErase: {erase}\nSegmenty:\n{segments}")

    def remove_selected(self):
        rows=sorted({i.row() for i in self.vbf_table.selectedIndexes()},reverse=True)
        for row in rows:
            if 0<=row<len(self.backend.entries): self.backend.entries.pop(row)
        self._sync_entries()

    def clear_vbfs(self): self.backend.entries.clear(); self.backend.sbl=None; self.vbf_table.setRowCount(0); self.vbf_details.clear()

    def move_entry(self, delta):
        row=self.vbf_table.currentRow(); new=row+delta
        if row<0 or new<0 or new>=len(self.backend.entries): return
        self.backend.entries[row],self.backend.entries[new]=self.backend.entries[new],self.backend.entries[row]
        self._sync_entries(); self.vbf_table.selectRow(new)

    def _sync_entries(self):
        self.backend.sbl=next((e for e in self.backend.entries if 'SBL' in e.kind.upper() or '14C025' in e.part_number),None)
        self.populate_vbf_table(self.backend.entries)

    def connect_ecu(self):
        try: self.backend.connect(self.selected_interface(),int(self.ecu_edit.text().strip(),0))
        except Exception as exc: QMessageBox.critical(self,"Połączenie",str(exc))

    def start_worker(self, fn):
        if self.thread is not None: QMessageBox.warning(self,"Zajęty","Inna operacja jest już uruchomiona."); return
        thread=QThread(self); worker=Worker(fn); self.worker=worker; worker.moveToThread(thread)
        thread.started.connect(worker.run); worker.failed.connect(self.worker_failed); worker.finished.connect(thread.quit); worker.finished.connect(worker.deleteLater)
        thread.finished.connect(thread.deleteLater); thread.finished.connect(self.worker_done); self.thread=thread
        self.flash_btn.setEnabled(False); self.unlock_btn.setEnabled(False); self.eeprom_read_btn.setEnabled(False); self.eeprom_write_btn.setEnabled(False); self.cancel_btn.setEnabled(True); thread.start()

    @Slot(str)
    def worker_failed(self,text): self.append_log("[!] Błąd operacji:\n"+text); QMessageBox.critical(self,"Błąd",text)
    @Slot()
    def worker_done(self): self.thread=None; self.worker=None; self.flash_btn.setEnabled(True); self.unlock_btn.setEnabled(True); self.eeprom_read_btn.setEnabled(True); self.eeprom_write_btn.setEnabled(True); self.cancel_btn.setEnabled(False)

    def unlock_test(self):
        try: interface=self.selected_interface(); ecu=int(self.ecu_edit.text().strip(),0); level=self.security_level.value()
        except Exception as exc: QMessageBox.critical(self,"Test unlock",str(exc)); return
        def task():
            self.backend.connect(interface,ecu)
            try: self.backend.unlock_test(level)
            finally: self.backend.disconnect()
        self.append_log("[*] Uruchamiam test odblokowania..."); self.start_worker(task)

    def start_flash(self):
        if QMessageBox.warning(self,"Potwierdzenie flashowania","Przerwanie zasilania może unieruchomić moduł. Kontynuować?",QMessageBox.Yes|QMessageBox.No,QMessageBox.No)!=QMessageBox.Yes:return
        try: interface=self.selected_interface()
        except Exception as exc: QMessageBox.critical(self,"Flashowanie",str(exc)); return
        self.append_log("[*] Uruchamiam flashowanie..."); self.start_worker(lambda:self.backend.flash_all(interface))

    def read_eeprom(self):
        if self.backend.sbl is None:
            QMessageBox.warning(self,"EEPROM","Najpierw dodaj SBL VBF (plik 14C025).")
            return
        try:
            interface=self.selected_interface()
            profile=str(self.eeprom_profile.currentData())
        except Exception as exc:
            QMessageBox.critical(self,"EEPROM",str(exc)); return
        default_name="GM2T_EEPROM_backup.bin"
        path,_=QFileDialog.getSaveFileName(
            self,"Zapisz kopię EEPROM",str(Path.home()/default_name),"BIN (*.bin);;Wszystkie pliki (*)"
        )
        if not path: return
        answer=QMessageBox.question(
            self,"Odczyt EEPROM",
            "Program sprawdzi SBL GM2T (0x35C / 0x40003600), załaduje go i wykona wyłącznie RequestUpload 0x1000 bajtów z adresu 0x02000000. Kontynuować?",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No
        )
        if answer!=QMessageBox.Yes: return
        self.append_log("[*] Uruchamiam bezpieczny odczyt EEPROM...")
        self.start_worker(lambda:self.backend.read_ipc_eeprom(interface,path,profile))

    def write_eeprom(self):
        if self.backend.sbl is None:
            QMessageBox.warning(self,"EEPROM","Najpierw dodaj SBL VBF (plik 14C025).")
            return
        try:
            interface=self.selected_interface()
            profile=str(self.eeprom_profile.currentData())
        except Exception as exc:
            QMessageBox.critical(self,"EEPROM",str(exc)); return
        source,_=QFileDialog.getOpenFileName(
            self,"Wybierz EEPROM.bin do zapisania",str(Path.home()),"BIN (*.bin);;Wszystkie pliki (*)"
        )
        if not source: return
        try:
            file_size=Path(source).stat().st_size
        except Exception as exc:
            QMessageBox.critical(self,"EEPROM",str(exc)); return
        if file_size != 0x1000:
            QMessageBox.critical(self,"EEPROM",f"Plik musi mieć dokładnie 4096 bajtów. Ma {file_size} B.")
            return
        default_backup=str(Path(source).with_name(Path(source).stem+"_before_write_backup.bin"))
        backup,_=QFileDialog.getSaveFileName(
            self,"Gdzie zapisać automatyczny backup",default_backup,"BIN (*.bin);;Wszystkie pliki (*)"
        )
        if not backup: return
        answer=QMessageBox.warning(
            self,"Kasowanie i zapis EEPROM",
            "Program najpierw odczyta i zapisze backup bieżącego EEPROM-u, następnie skasuje obszar 0x02000000/0x1000 i wgra wybrany plik 4096 B. Przerwanie zasilania podczas zapisu może unieruchomić licznik. Kontynuować?",
            QMessageBox.Yes|QMessageBox.No,QMessageBox.No
        )
        if answer!=QMessageBox.Yes: return
        self.append_log("[*] Uruchamiam bezpośredni zapis EEPROM.bin...")
        self.start_worker(lambda:self.backend.write_ipc_eeprom(interface,source,backup,profile))

    def send_uds(self):
        try: payload=bytes.fromhex(self.uds_input.text());
        except Exception as exc: QMessageBox.critical(self,"UDS",str(exc)); return
        def task():
            response=self.backend.uds_request(payload); self.uds_signal.emit(payload,response)
        self.start_worker(task)

    @Slot(bytes,bytes)
    def show_uds(self,payload,response): self.uds_output.appendPlainText(f"> {payload.hex(' ').upper()}\n< {response.hex(' ').upper() if response else 'BRAK ODPOWIEDZI'}\n")

    def read_info(self):
        try:
            interface = self.selected_interface()
            ecu_id = int(self.ecu_edit.text().strip(), 0)
        except Exception as exc:
            QMessageBox.critical(self, "ECU Info", str(exc))
            return

        def task():
            opened_here = self.backend.ecu is None
            if opened_here:
                self.backend.connect(interface, ecu_id)
            try:
                self.info_signal.emit(self.backend.read_info())
            finally:
                if opened_here:
                    self.backend.disconnect()

        self.append_log("[*] Odczytuję informacje ECU...")
        self.start_worker(task)
    @Slot(dict)
    def show_info(self,info):
        self.info_table.setRowCount(len(info))
        for row,(k,v) in enumerate(info.items()): self.info_table.setItem(row,0,QTableWidgetItem(k)); self.info_table.setItem(row,1,QTableWidgetItem(v))

    def start_can_monitor(self):
        try: interface=self.selected_interface()
        except Exception as exc: QMessageBox.critical(self,"CAN",str(exc)); return
        self.can_stop.clear()
        def on_frame(msg):
            stamp=datetime.now().strftime('%H:%M:%S.%f')[:-3]; data=' '.join(f'{b:02X}' for b in msg.data)
            self.can_signal.emit(f"{stamp}  {msg.arbitration_id:03X}  [{msg.dlc}]  {data}")
        self.start_worker(lambda:self.backend.monitor_can(interface,on_frame,self.can_stop))
    def stop_can_monitor(self): self.can_stop.set()
    @Slot(str)
    def append_can(self,text): self.can_output.appendPlainText(text)

    def save_log(self): self._save_text(self.log.toPlainText(),'ford_uds_studio.log')
    def save_can_log(self): self._save_text(self.can_output.toPlainText(),'can_monitor.log')
    def _save_text(self,text,default):
        path,_=QFileDialog.getSaveFileName(self,"Zapisz log",str(Path.home()/default),"Log (*.log);;Tekst (*.txt)")
        if path: Path(path).write_text(text,encoding='utf-8')

    @Slot(str)
    def append_log(self,text): self.log.appendPlainText(text); self.security_output.appendPlainText(text); self.statusBar().showMessage(text.splitlines()[-1] if text else '')
    @Slot(int,int,str)
    def update_progress(self, current, total, text):
        total = max(1, int(total))
        current = max(0, min(int(current), total))
        percent = int((current * 100) / total)
        self.progress.setRange(0, 100)
        self.progress.setValue(percent)
        label = text.split(":", 1)[0].strip() if text else "Postęp"
        if percent >= 100:
            self.progress_label.setText(f"{label}: 100%")
        else:
            self.progress_label.setText(f"{label}: {percent}%")

    def closeEvent(self,event): self.can_stop.set(); self.backend.cancel(); self.backend.disconnect(); event.accept()


def main():
    app=QApplication(sys.argv); app.setApplicationName("Ford UDS Studio"); window=MainWindow(); window.show(); return app.exec()

if __name__=='__main__': raise SystemExit(main())
