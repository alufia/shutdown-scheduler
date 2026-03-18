import json
import os
import subprocess
import sys
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from PySide6.QtCore import QDateTime, QTimer, Qt
from PySide6.QtGui import QFont, QIcon
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QDateTimeEdit,
    QDialog,
    QFrame,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QMessageBox,
    QPushButton,
    QVBoxLayout,
    QWidget,
)


APP_NAME = "Shutdown Scheduler"
WINDOW_TITLE = "Shutdown Scheduler"
APP_DIR = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "ShutdownScheduler"
STATE_FILE = APP_DIR / "schedule.json"
TASK_NAME = "ShutdownScheduler_UserTask_v2"
CREATE_NO_WINDOW = 0x08000000 if os.name == "nt" else 0


@dataclass
class ScheduleState:
    target_iso: str
    force_close: bool

    @property
    def target(self) -> datetime:
        return datetime.fromisoformat(self.target_iso)


def ensure_app_dir() -> None:
    APP_DIR.mkdir(parents=True, exist_ok=True)


def load_state() -> ScheduleState | None:
    if not STATE_FILE.exists():
        return None

    try:
        payload = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        state = ScheduleState(
            target_iso=payload["target_iso"],
            force_close=bool(payload.get("force_close", False)),
        )
        if state.target <= datetime.now():
            clear_state()
            return None
        return state
    except Exception:
        clear_state()
        return None


def save_state(state: ScheduleState) -> None:
    ensure_app_dir()
    STATE_FILE.write_text(
        json.dumps(
            {
                "target_iso": state.target_iso,
                "force_close": state.force_close,
            },
            ensure_ascii=False,
            indent=2,
        ),
        encoding="utf-8",
    )


def clear_state() -> None:
    if STATE_FILE.exists():
        STATE_FILE.unlink()


def resource_path(*parts: str) -> Path:
    base = Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parent))
    return base.joinpath(*parts)


def app_icon() -> QIcon:
    icon_path = resource_path("assets", "shutdown_scheduler.ico")
    if icon_path.exists():
        return QIcon(str(icon_path))
    return QIcon()


def run_shutdown_command(args: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["shutdown", *args],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except FileNotFoundError:
        return False, "윈도우의 shutdown 명령을 찾지 못했습니다."
    except Exception as exc:
        return False, f"명령 실행 중 오류가 발생했습니다: {exc}"

    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode == 0:
        return True, output
    return False, output or f"종료 예약 명령이 실패했습니다. 코드: {completed.returncode}"


def run_schtasks_command(args: list[str]) -> tuple[bool, str]:
    try:
        completed = subprocess.run(
            ["schtasks", *args],
            capture_output=True,
            text=True,
            creationflags=CREATE_NO_WINDOW,
            check=False,
        )
    except FileNotFoundError:
        return False, "윈도우의 schtasks 명령을 찾지 못했습니다."
    except Exception as exc:
        return False, f"schtasks 실행 중 오류가 발생했습니다: {exc}"

    output = (completed.stdout or completed.stderr or "").strip()
    if completed.returncode == 0:
        return True, output
    return False, output or f"schtasks 명령이 실패했습니다. 코드: {completed.returncode}"


def create_scheduled_task(target: datetime, force_close: bool) -> tuple[bool, str]:
    action_args = "/s /t 0 /f" if force_close else "/s /t 0"
    normalized_target = target.replace(second=0, microsecond=0)
    return run_schtasks_command(
        [
            "/Create",
            "/TN",
            TASK_NAME,
            "/SC",
            "ONCE",
            "/SD",
            normalized_target.strftime("%m/%d/%Y"),
            "/ST",
            normalized_target.strftime("%H:%M"),
            "/TR",
            f"shutdown.exe {action_args}",
            "/F",
        ]
    )


def remove_scheduled_task() -> tuple[bool, str]:
    ok, output = run_schtasks_command(["/Delete", "/TN", TASK_NAME, "/F"])
    if ok:
        return True, output
    lowered = output.lower()
    if "cannot find the file" in lowered or "cannot find the system specified" in lowered:
        return True, ""
    if "cannot find the specified file" in lowered or "the system cannot find" in lowered:
        return True, ""
    return False, output


def query_task_state() -> tuple[bool, ScheduleState | None]:
    ok, output = run_schtasks_command(["/Query", "/TN", TASK_NAME, "/XML"])
    if not ok:
        lowered = output.lower()
        if "cannot find the file" in lowered or "cannot find the specified file" in lowered:
            return True, None
        if "system cannot find" in lowered:
            return True, None
        return False, None
    if not output:
        return True, None

    try:
        root = ET.fromstring(output)
        ns = {"task": "http://schemas.microsoft.com/windows/2004/02/mit/task"}
        start_boundary = root.findtext(".//task:TimeTrigger/task:StartBoundary", namespaces=ns)
        arguments = root.findtext(".//task:Exec/task:Arguments", default="", namespaces=ns)
        if not start_boundary:
            return True, None
        state = ScheduleState(
            target_iso=datetime.fromisoformat(start_boundary).isoformat(),
            force_close="/f" in arguments.lower(),
        )
        if state.target <= datetime.now():
            return True, None
        save_state(state)
        return True, state
    except Exception:
        return False, None


def get_active_schedule() -> ScheduleState | None:
    task_query_ok, task_state = query_task_state()
    if task_query_ok:
        if task_state is None:
            clear_state()
        return task_state
    return load_state()


def schedule_shutdown(target: datetime, force_close: bool) -> tuple[bool, str]:
    seconds = int((target - datetime.now()).total_seconds())
    if seconds < 1:
        return False, "현재 시각보다 미래 시간을 선택해 주세요."

    remove_scheduled_task()
    run_shutdown_command(["/a"])

    shutdown_args = ["/s", "/t", str(seconds)]
    if force_close:
        shutdown_args.append("/f")

    queue_ok, queue_message = run_shutdown_command(shutdown_args)
    task_ok, task_message = create_scheduled_task(target, force_close)

    if queue_ok or task_ok:
        save_state(ScheduleState(target_iso=target.isoformat(), force_close=force_close))
        return True, queue_message or task_message

    message_parts = [part for part in (queue_message, task_message) if part]
    return False, "\n".join(message_parts) or "종료 예약을 적용하지 못했습니다."


def abort_shutdown() -> tuple[bool, str]:
    task_ok, task_message = remove_scheduled_task()
    shutdown_ok, shutdown_message = run_shutdown_command(["/a"])
    clear_state()

    if task_ok or shutdown_ok:
        return True, task_message or shutdown_message
    return False, task_message or shutdown_message


def format_target(dt: datetime) -> str:
    return dt.strftime("%Y-%m-%d %H:%M")


def format_remaining(target: datetime) -> str:
    remaining = target - datetime.now()
    total_seconds = max(int(remaining.total_seconds()), 0)
    days, remainder = divmod(total_seconds, 86400)
    hours, remainder = divmod(remainder, 3600)
    minutes, seconds = divmod(remainder, 60)
    if days:
        return f"{days}일 {hours}시간 {minutes}분 남음"
    if hours:
        return f"{hours}시간 {minutes}분 {seconds}초 남음"
    if minutes:
        return f"{minutes}분 {seconds}초 남음"
    return f"{seconds}초 남음"


class FeedbackDialog(QDialog):
    def __init__(
        self,
        parent: QWidget | None,
        *,
        title: str,
        message: str,
        detail: str | None,
        accent: str,
    ) -> None:
        super().__init__(parent)
        self.setWindowTitle(title)
        self.setWindowIcon(app_icon())
        self.setModal(True)
        self.setFixedWidth(340)
        self.setObjectName("feedbackDialog")

        layout = QVBoxLayout(self)
        layout.setContentsMargins(18, 18, 18, 18)
        layout.setSpacing(14)

        header = QHBoxLayout()
        header.setSpacing(12)

        icon_label = QLabel()
        icon_label.setObjectName("feedbackIcon")
        icon_label.setFixedSize(44, 44)
        icon_label.setPixmap(app_icon().pixmap(24, 24))
        icon_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        title_block = QVBoxLayout()
        title_block.setSpacing(2)

        title_label = QLabel(title)
        title_label.setObjectName("feedbackTitle")

        subtitle_label = QLabel("Shutdown Scheduler")
        subtitle_label.setObjectName("feedbackSubtitle")

        title_block.addWidget(title_label)
        title_block.addWidget(subtitle_label)
        header.addWidget(icon_label)
        header.addLayout(title_block)
        header.addStretch()

        message_label = QLabel(message)
        message_label.setObjectName("feedbackMessage")
        message_label.setWordWrap(True)

        layout.addLayout(header)
        layout.addWidget(message_label)

        if detail:
            detail_label = QLabel(detail)
            detail_label.setObjectName("feedbackDetail")
            detail_label.setWordWrap(True)
            layout.addWidget(detail_label)

        button_row = QHBoxLayout()
        button_row.addStretch()
        confirm_button = QPushButton("확인")
        confirm_button.clicked.connect(self.accept)
        button_row.addWidget(confirm_button)
        layout.addLayout(button_row)

        self.setStyleSheet(
            f"""
            QDialog#feedbackDialog {{
                background: #FFFDFC;
                border: 1px solid #E3D9CC;
                border-radius: 20px;
            }}
            QLabel#feedbackIcon {{
                background: {accent};
                border-radius: 14px;
                color: #F8F4ED;
            }}
            QLabel#feedbackTitle {{
                color: #152532;
                font-size: 16px;
                font-weight: 800;
            }}
            QLabel#feedbackSubtitle {{
                color: #7C6F61;
                font-size: 11px;
                font-weight: 700;
            }}
            QLabel#feedbackMessage {{
                color: #23313C;
                font-size: 13px;
                font-weight: 600;
            }}
            QLabel#feedbackDetail {{
                color: #625C54;
                font-size: 12px;
            }}
            QDialog#feedbackDialog QPushButton {{
                background: {accent};
                color: #F8F4ED;
                border: none;
                border-radius: 12px;
                padding: 8px 16px;
                min-width: 84px;
                font-size: 12px;
                font-weight: 800;
            }}
            QDialog#feedbackDialog QPushButton:hover {{
                background: #2F556E;
            }}
            """
        )


class SchedulerWindow(QMainWindow):
    def __init__(self) -> None:
        super().__init__()
        self.setWindowTitle(WINDOW_TITLE)
        self.resize(860, 540)
        self.setMinimumSize(860, 540)
        self.setWindowIcon(app_icon())
        self.state: ScheduleState | None = None

        self.clock_timer = QTimer(self)
        self.clock_timer.timeout.connect(self.refresh_live_status)
        self.clock_timer.start(1000)

        self.sync_timer = QTimer(self)
        self.sync_timer.timeout.connect(self.sync_state_from_system)
        self.sync_timer.start(25000)

        self._build_ui()
        self._apply_styles()
        app = QApplication.instance()
        if app is not None:
            app.applicationStateChanged.connect(self.handle_app_state_change)
        self.sync_state_from_system(force=True)
        self.refresh_live_status()

    def _build_ui(self) -> None:
        root = QWidget()
        root.setObjectName("root")
        root_layout = QHBoxLayout(root)
        root_layout.setContentsMargins(20, 20, 20, 20)
        root_layout.setSpacing(16)

        left_panel = self._build_hero_panel()
        right_panel = self._build_control_panel()

        root_layout.addWidget(left_panel, 4)
        root_layout.addWidget(right_panel, 5)
        self.setCentralWidget(root)

    def _make_card(self) -> QFrame:
        card = QFrame()
        return card

    def _build_hero_panel(self) -> QWidget:
        card = self._make_card()
        card.setObjectName("heroCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        brand_row = QHBoxLayout()
        brand_row.setSpacing(12)

        brand_icon = QLabel()
        brand_icon.setObjectName("brandIcon")
        brand_icon.setFixedSize(52, 52)
        brand_icon.setPixmap(app_icon().pixmap(30, 30))
        brand_icon.setAlignment(Qt.AlignmentFlag.AlignCenter)

        brand_text_layout = QVBoxLayout()
        brand_text_layout.setSpacing(2)

        brand_label = QLabel("Shutdown Scheduler")
        brand_label.setObjectName("brandLabel")

        badge = QLabel("SMART TIMER")
        badge.setObjectName("badge")

        brand_text_layout.addWidget(brand_label)
        brand_text_layout.addWidget(badge)
        brand_row.addWidget(brand_icon)
        brand_row.addLayout(brand_text_layout)
        brand_row.addStretch()

        title = QLabel("PC 종료 예약")
        title.setObjectName("title")

        subtitle = QLabel(
            "한 번 설정하면 윈도우에 바로 등록되고,\n"
            "앱을 닫아도 예약 상태가 그대로 이어집니다."
        )
        subtitle.setObjectName("subtitle")
        subtitle.setWordWrap(True)

        info_card = QFrame()
        info_card.setObjectName("infoCard")
        info_layout = QVBoxLayout(info_card)
        info_layout.setContentsMargins(18, 18, 18, 18)
        info_layout.setSpacing(8)

        self.now_label = QLabel()
        self.now_label.setObjectName("metricPrimary")
        self.remaining_label = QLabel()
        self.remaining_label.setObjectName("metricSecondary")
        self.schedule_label = QLabel()
        self.schedule_label.setObjectName("scheduleSummary")
        self.schedule_label.setWordWrap(True)

        info_layout.addWidget(QLabel("현재 시각"))
        info_layout.addWidget(self.now_label)
        info_layout.addSpacing(6)
        info_layout.addWidget(QLabel("예약 상태"))
        info_layout.addWidget(self.remaining_label)
        info_layout.addWidget(self.schedule_label)

        feature_note = QLabel("빠른 실행 버튼으로 즉시 잡거나, 원하는 날짜와 시간을 정교하게 고를 수 있습니다.")
        feature_note.setObjectName("heroNote")
        feature_note.setWordWrap(True)

        layout.addLayout(brand_row)
        layout.addWidget(title)
        layout.addWidget(subtitle)
        layout.addSpacing(4)
        layout.addWidget(info_card)
        layout.addStretch()
        layout.addWidget(feature_note)
        return card

    def _build_control_panel(self) -> QWidget:
        card = self._make_card()
        card.setObjectName("controlCard")
        layout = QVBoxLayout(card)
        layout.setContentsMargins(24, 24, 24, 24)
        layout.setSpacing(14)

        header = QLabel("예약 설정")
        header.setObjectName("sectionTitle")

        description = QLabel("깔끔한 한 화면에서 종료 시각, 빠른 예약, 강제 종료 옵션까지 바로 설정합니다.")
        description.setObjectName("sectionDescription")
        description.setWordWrap(True)

        date_label = QLabel("종료 날짜 및 시간")
        date_label.setObjectName("fieldLabel")

        self.datetime_edit = QDateTimeEdit()
        self.datetime_edit.setCalendarPopup(True)
        self.datetime_edit.setDisplayFormat("yyyy-MM-dd HH:mm")
        self.datetime_edit.setDateTime(QDateTime.currentDateTime().addSecs(1800))
        self.datetime_edit.setMinimumDateTime(QDateTime.currentDateTime().addSecs(60))
        self.datetime_edit.dateTimeChanged.connect(self.refresh_preview)

        quick_row = QHBoxLayout()
        quick_row.setSpacing(10)

        self.quick_30 = QPushButton("30분 뒤")
        self.quick_1h = QPushButton("1시간 뒤")
        self.quick_2h = QPushButton("2시간 뒤")
        self.quick_midnight = QPushButton("오늘 23:00")

        self.quick_30.clicked.connect(lambda: self.set_quick_time(minutes=30))
        self.quick_1h.clicked.connect(lambda: self.set_quick_time(hours=1))
        self.quick_2h.clicked.connect(lambda: self.set_quick_time(hours=2))
        self.quick_midnight.clicked.connect(self.set_tonight)

        for button in (self.quick_30, self.quick_1h, self.quick_2h, self.quick_midnight):
            button.setObjectName("quickButton")
            quick_row.addWidget(button)

        self.force_checkbox = QCheckBox("열려 있는 앱도 자동으로 닫고 확실히 종료")
        self.force_checkbox.setChecked(True)
        self.force_checkbox.stateChanged.connect(self.refresh_preview)

        preview_card = QFrame()
        preview_card.setObjectName("previewCard")
        preview_layout = QVBoxLayout(preview_card)
        preview_layout.setContentsMargins(16, 14, 16, 14)
        preview_layout.setSpacing(6)

        preview_title = QLabel("예약 미리보기")
        preview_title.setObjectName("previewTitle")
        self.preview_label = QLabel()
        self.preview_label.setObjectName("previewValue")
        self.preview_label.setWordWrap(True)

        preview_layout.addWidget(preview_title)
        preview_layout.addWidget(self.preview_label)

        button_row = QHBoxLayout()
        button_row.setSpacing(12)

        self.schedule_button = QPushButton("종료 예약 시작")
        self.schedule_button.setObjectName("primaryButton")
        self.schedule_button.clicked.connect(self.handle_schedule)

        self.cancel_button = QPushButton("예약 취소")
        self.cancel_button.setObjectName("secondaryButton")
        self.cancel_button.clicked.connect(self.handle_cancel)

        button_row.addWidget(self.schedule_button)
        button_row.addWidget(self.cancel_button)

        self.footer_note = QLabel("예약 후 앱을 닫아도 예약은 유지됩니다.")
        self.footer_note.setObjectName("footerNote")

        layout.addWidget(header)
        layout.addWidget(description)
        layout.addSpacing(8)
        layout.addWidget(date_label)
        layout.addWidget(self.datetime_edit)
        layout.addLayout(quick_row)
        layout.addWidget(self.force_checkbox)
        layout.addWidget(preview_card)
        layout.addStretch()
        layout.addLayout(button_row)
        layout.addWidget(self.footer_note)

        self.refresh_preview()
        return card

    def _apply_styles(self) -> None:
        font = QFont("Segoe UI Variable Text", 10)
        QApplication.instance().setFont(font)
        self.setStyleSheet(
            """
            QWidget#root {
                background: #EEE8E0;
            }
            QWidget {
                color: #1F2A33;
            }
            QFrame#heroCard {
                background: #142533;
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 24px;
            }
            QFrame#heroCard QLabel {
                color: #F5EFE7;
            }
            QFrame#controlCard {
                background: #FFFDFC;
                border: 1px solid #E3D9CC;
                border-radius: 24px;
            }
            QLabel#brandLabel {
                color: #F5EFE7;
                font-size: 13px;
                font-weight: 700;
            }
            QLabel#brandIcon {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.08);
                border-radius: 16px;
            }
            QLabel#badge {
                color: #E7C48F;
                font-size: 11px;
                font-weight: 700;
                letter-spacing: 1px;
            }
            QLabel#title {
                color: #F5EFE7;
                font-size: 28px;
                font-weight: 800;
            }
            QLabel#subtitle {
                color: rgba(245, 239, 231, 0.78);
                font-size: 13px;
            }
            QLabel#sectionDescription, QLabel#footerNote {
                color: #625C54;
                font-size: 13px;
            }
            QLabel#heroNote {
                color: rgba(245, 239, 231, 0.72);
                font-size: 12px;
            }
            QFrame#infoCard, QFrame#previewCard {
                border-radius: 18px;
            }
            QFrame#infoCard {
                background: rgba(255, 255, 255, 0.08);
                border: 1px solid rgba(255, 255, 255, 0.10);
            }
            QFrame#infoCard QLabel {
                color: rgba(245, 239, 231, 0.78);
            }
            QFrame#previewCard {
                background: #F5EFE7;
                border: 1px solid #E3D9CC;
                border-radius: 16px;
            }
            QLabel#metricPrimary {
                color: #F8F4ED;
                font-size: 20px;
                font-weight: 700;
            }
            QLabel#metricSecondary {
                color: #9CE3B4;
                font-size: 18px;
                font-weight: 700;
            }
            QLabel#scheduleSummary {
                color: rgba(245, 239, 231, 0.84);
                font-size: 12px;
            }
            QLabel#sectionTitle {
                color: #152532;
                font-size: 21px;
                font-weight: 800;
            }
            QLabel#fieldLabel, QLabel#previewTitle {
                font-size: 12px;
                font-weight: 700;
                color: #56606A;
            }
            QLabel#previewValue {
                font-size: 14px;
                color: #152532;
            }
            QDateTimeEdit {
                background: #FFFDFC;
                color: #152532;
                border: 1px solid #D4C6B8;
                border-radius: 14px;
                padding: 10px 14px;
                font-size: 15px;
                min-height: 22px;
            }
            QDateTimeEdit:focus {
                border: 1px solid #1E3A4C;
            }
            QDateTimeEdit::drop-down {
                border: none;
                width: 32px;
            }
            QCheckBox {
                spacing: 10px;
                font-size: 13px;
                color: #23313C;
            }
            QCheckBox::indicator {
                width: 16px;
                height: 16px;
            }
            QCheckBox::indicator:unchecked {
                border: 1px solid #B7AA9A;
                border-radius: 6px;
                background: #FFFDFC;
            }
            QCheckBox::indicator:checked {
                border: 1px solid #1E3A4C;
                border-radius: 6px;
                background: #1E3A4C;
            }
            QPushButton {
                border: none;
                border-radius: 14px;
                padding: 11px 16px;
                font-size: 13px;
                font-weight: 700;
            }
            QPushButton#primaryButton {
                background: #1E3A4C;
                color: #F7F4EE;
            }
            QPushButton#primaryButton:hover {
                background: #284B63;
            }
            QPushButton#secondaryButton {
                background: #EFE6DB;
                color: #23313C;
                border: 1px solid #D9CDBE;
            }
            QPushButton#secondaryButton:hover, QPushButton#quickButton:hover {
                background: #E8DCCB;
            }
            QPushButton#quickButton {
                background: #FFFDFC;
                color: #23313C;
                border: 1px solid #D9CDBE;
                padding: 10px 12px;
            }
            """
        )

    def show_feedback(
        self,
        title: str,
        message: str,
        *,
        icon: QMessageBox.Icon,
        detail: str | None = None,
    ) -> None:
        accent = {
            QMessageBox.Icon.Information: "#1E3A4C",
            QMessageBox.Icon.Warning: "#C8872D",
            QMessageBox.Icon.Critical: "#9F4939",
        }.get(icon, "#1E3A4C")
        dialog = FeedbackDialog(self, title=title, message=message, detail=detail, accent=accent)
        dialog.exec()

    def handle_app_state_change(self, state: Qt.ApplicationState) -> None:
        if state == Qt.ApplicationActive:
            self.sync_state_from_system(force=True)

    def refresh_preview(self) -> None:
        target = self.datetime_edit.dateTime().toPython()
        mode = "강제 종료 켜짐" if self.force_checkbox.isChecked() else "강제 종료 꺼짐"
        self.preview_label.setText(
            f"{format_target(target)}에 종료됩니다.\n"
            f"현재 기준으로 {format_remaining(target)}\n"
            f"{mode}"
        )

    def refresh_live_status(self) -> None:
        now = datetime.now()
        self.now_label.setText(now.strftime("%Y-%m-%d %H:%M:%S"))
        self.datetime_edit.setMinimumDateTime(QDateTime.currentDateTime().addSecs(60))

        if self.state and self.state.target <= now:
            self.state = None
            clear_state()

        if self.state:
            self.remaining_label.setText(format_remaining(self.state.target))
            force_text = "강제 종료 켜짐" if self.state.force_close else "강제 종료 꺼짐"
            self.schedule_label.setText(
                f"{format_target(self.state.target)} 예약됨\n{force_text}"
            )
        else:
            self.remaining_label.setText("현재 예약 없음")
            self.schedule_label.setText("원하는 날짜와 시간을 선택해 종료 예약을 시작하세요.")

        self.refresh_preview()

    def sync_state_from_system(self, *, force: bool = False) -> None:
        latest_state = get_active_schedule()
        if not force and latest_state == self.state:
            return

        self.state = latest_state
        if self.state:
            self.datetime_edit.blockSignals(True)
            self.force_checkbox.blockSignals(True)
            self.datetime_edit.setDateTime(QDateTime(self.state.target))
            self.force_checkbox.setChecked(self.state.force_close)
            self.force_checkbox.blockSignals(False)
            self.datetime_edit.blockSignals(False)
        self.refresh_live_status()

    def set_quick_time(self, *, minutes: int = 0, hours: int = 0) -> None:
        target = datetime.now() + timedelta(minutes=minutes, hours=hours)
        self.datetime_edit.setDateTime(QDateTime(target))

    def set_tonight(self) -> None:
        now = datetime.now()
        target = now.replace(hour=23, minute=0, second=0, microsecond=0)
        if target <= now:
            target = target + timedelta(days=1)
        self.datetime_edit.setDateTime(QDateTime(target))

    def handle_schedule(self) -> None:
        target = self.datetime_edit.dateTime().toPython()
        force_close = self.force_checkbox.isChecked()
        ok, message = schedule_shutdown(target, force_close)
        if ok:
            self.state = ScheduleState(target_iso=target.isoformat(), force_close=force_close)
            self.refresh_live_status()
            self.show_feedback(
                "예약 완료",
                f"{format_target(target)}에 종료 예약을 걸었습니다.\n앱을 닫아도 예약은 그대로 유지됩니다.",
                icon=QMessageBox.Icon.Information,
            )
            return

        self.show_feedback(
            "예약 실패",
            "종료 예약을 적용하지 못했습니다.",
            icon=QMessageBox.Icon.Critical,
            detail=message or "종료 예약 중 문제가 발생했습니다.",
        )

    def handle_cancel(self) -> None:
        ok, message = abort_shutdown()
        if ok:
            self.state = None
            self.refresh_live_status()
            self.show_feedback(
                "예약 취소",
                "기존 종료 예약을 취소했습니다.",
                icon=QMessageBox.Icon.Information,
            )
            return

        self.show_feedback(
            "취소 실패",
            "취소할 종료 예약이 없거나 취소에 실패했습니다.",
            icon=QMessageBox.Icon.Warning,
            detail=message,
        )


def self_test() -> int:
    ensure_app_dir()
    future = datetime.now() + timedelta(minutes=45)
    sample = ScheduleState(target_iso=future.isoformat(), force_close=True)
    save_state(sample)
    loaded = load_state()
    assert loaded is not None
    assert loaded.force_close is True
    assert loaded.target_iso == sample.target_iso
    clear_state()
    assert load_state() is None
    print("self-test-ok")
    return 0


def main() -> int:
    if "--self-test" in sys.argv:
        return self_test()

    app = QApplication(sys.argv)
    app.setApplicationName(APP_NAME)
    app.setWindowIcon(app_icon())
    window = SchedulerWindow()
    window.show()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
