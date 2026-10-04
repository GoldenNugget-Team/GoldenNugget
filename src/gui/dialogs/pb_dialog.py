import asyncio

from PySide6.QtWidgets import QWizard, QWizardPage, QLabel, QVBoxLayout, QProgressBar, QSizePolicy, QMessageBox
from PySide6.QtCore import QSize, Qt

from src.exceptions.nugget_exception import NuggetException
from src.gui.thread_workers.apply_worker import ApplyAlertMessage
from src.gui.thread_workers.pb_worker import PBDBThread
from src.tweaks.tweaks import tweaks, TweakID

class PosterBoardDBWizard(QWizard):
    def __init__(self, udid: str, pbDBLbl: QLabel, update_savedIds_list=lambda x: None):
        super().__init__()
        self.udid = udid
        self.pbDBLbl = pbDBLbl
        self.backup_in_progress = False
        self.backup_successful = False
        # set by the worker thread, shown on the GUI thread once it finishes
        self.backup_failure: str | None = None
        self.update_savedIds_list = update_savedIds_list

        # only show cancel and next/finish buttons
        self.setOption(QWizard.WizardOption.NoBackButtonOnStartPage, True)
        self.setOption(QWizard.WizardOption.NoBackButtonOnLastPage, True)
        self.setButtonLayout([QWizard.WizardButton.CancelButton, QWizard.WizardButton.Stretch, QWizard.WizardButton.NextButton])

        # progress bar for the backup progress
        self.backupInfoLbl = QLabel("Please enter your password on your device to continue")
        self.progressBar = QProgressBar()
        sizePolicy = QSizePolicy()
        sizePolicy.setHeightForWidth(self.progressBar.sizePolicy().hasHeightForWidth())
        self.progressBar.setSizePolicy(sizePolicy)
        self.progressBar.setMinimumSize(QSize(250, 0))
        self.progressBar.setValue(0)
        self.progressBar.setAlignment(Qt.AlignCenter)

        self.addPage(self.createPage1())
        self.addPage(self.createBackupProgPage())
        self.addPage(self.createFinalPage())

        self.setWindowTitle("Fetch Database File")

    # PAGES
    def createPage1(self) -> QWizardPage:
        # information page telling the user about backing up
        page = QWizardPage()
        page.setTitle("Notice")
        message = QLabel("GoldenNugget needs to download the PosterBoard database from your device.")
        contLbl = QLabel("\nYour device is not erased or wiped — only the PosterBoard data is fetched.")
        layout = QVBoxLayout(page)
        layout.addWidget(message)
        layout.addWidget(contLbl)
        page.setLayout(layout)
        return page
    
    def createFinalPage(self) -> QWizardPage:
        # just say whether backup was successful
        page = QWizardPage()
        page.setTitle("Backup Complete")
        message = QLabel("Successfully got the file")
        layout = QVBoxLayout(page)
        layout.addWidget(message)
        page.setLayout(layout)
        return page
    
    def createBackupProgPage(self) -> QWizardPage:
        # show the progress bar of the backup
        page = QWizardPage()
        page.setTitle("Backing Up Device...")
        layout = QVBoxLayout(page)
        layout.addWidget(self.backupInfoLbl)
        layout.addWidget(self.progressBar)
        page.setLayout(layout)
        return page
    
    def update_progress_bar(self, percent):
        print(f'backup progress: {percent}')
        if percent == 0.0:
            self.backupInfoLbl.setText("Preparing device for backup...")
        else:
            self.progressBar.setValue(int(percent))
            self.backupInfoLbl.setText(f'Backing up...  {percent:6.1f}%')

    def update_progress_lbl(self, txt: str):
        # hacky workaround
        if txt.startswith('sqlite'):
            self.pbDBLbl.setText(txt)
        else:
            self.backupInfoLbl.setText(txt)

    def finish_backup_thread(self):
        if self.backup_successful:
            self.update_savedIds_list()
            self.setButtonLayout([QWizard.WizardButton.Stretch, QWizard.WizardButton.NextButton])
        elif self.backup_failure:
            # "Backup Failed!" alone told the user nothing — say WHY (e.g. a torn
            # database copy) and what actually fixes it.
            QMessageBox.warning(self, self.windowTitle(), self.backup_failure)
        self.backup_in_progress = False
        # self.next()

    def alert_message(self, msg: ApplyAlertMessage):
        if msg.detailed_txt:
            QMessageBox.critical(self, msg.title, f"{msg.txt}\n\n{msg.detailed_txt}")
        else:
            QMessageBox.critical(self, msg.title, msg.txt)
    
    def start_device_backup(self, update_label=lambda x: None, update_progress=lambda x: None):
        asyncio.run(self._start_device_backup(update_label, update_progress))
    async def _start_device_backup(self, update_label=lambda x: None, update_progress=lambda x: None):
        try:
            # Local import: the restore chain pulls in pymobiledevice3, which
            # must not be loaded while the GUI is still starting up.
            from src.restore.posterboard_backup import targeted_posterboard_database_backup
            db_result = await targeted_posterboard_database_backup(self.udid, update_label, update_progress)
            if not tweaks[TweakID.PosterBoard].config_manager.update_database_file(
                    db_result[0], self.udid, structure_version=db_result[1]):
                raise NuggetException("The database is not of the correct format!")
            update_label("sqlite: Selected")

            # re-enable next button
            self.backup_successful = True
            update_label("Success!") # TODO: Place this somewhere else so that we can call self.next()
            # self.setButtonLayout([QWizard.WizardButton.Stretch, QWizard.WizardButton.NextButton])
        except Exception as e:
            # The pull retries a torn database copy on its own, so reaching here
            # means every attempt came back unusable — keep the reason for the
            # dialog the finish handler shows.
            self.backup_failure = getattr(e, "detailed_text", None) or str(e) or repr(e)
            update_label("Backup Failed!")
            print(repr(e))
    
    # OVERWRITTEN FUNCTIONS
    def initializePage(self, id):
        if id == 1:
            # start the backup
            # disable next button until backup is done
            self.setButtonLayout([QWizard.WizardButton.CancelButton, QWizard.WizardButton.Stretch])
            self.backup_in_progress = True
            self.backup_successful = False
            self.backup_failure = None
            self.worker_thread = PBDBThread(backup_function=self.start_device_backup)
            self.worker_thread.progress.connect(self.update_progress_bar)
            self.worker_thread.infoLbl.connect(self.update_progress_lbl)
            self.worker_thread.alert.connect(self.alert_message)
            self.worker_thread.finished.connect(self.finish_backup_thread)
            self.worker_thread.finished.connect(self.worker_thread.deleteLater)
            self.worker_thread.start()
        return super().initializePage(id)