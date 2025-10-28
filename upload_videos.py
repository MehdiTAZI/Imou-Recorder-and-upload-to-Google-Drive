import logging
import time
from pathlib import Path

import yaml
from pydrive2.auth import GoogleAuth
from pydrive2.drive import GoogleDrive

from queue_utils import enqueue_entry, dequeue_entry


class MaxLevelFilter(logging.Filter):
    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def setup_logging(stdout_path: Path, error_path: Path) -> logging.Logger:
    logger = logging.getLogger("upload")
    logger.setLevel(logging.INFO)

    for handler in list(logger.handlers):
        logger.removeHandler(handler)

    log_format = "%(asctime)s [%(levelname)s] %(message)s"
    stdout_path.parent.mkdir(parents=True, exist_ok=True)
    error_path.parent.mkdir(parents=True, exist_ok=True)

    stdout_handler = logging.FileHandler(stdout_path, encoding="utf-8")
    stdout_handler.setLevel(logging.INFO)
    stdout_handler.addFilter(MaxLevelFilter(logging.WARNING))
    stdout_handler.setFormatter(logging.Formatter(log_format))

    error_handler = logging.FileHandler(error_path, encoding="utf-8")
    error_handler.setLevel(logging.ERROR)
    error_handler.setFormatter(logging.Formatter(log_format))

    logger.addHandler(stdout_handler)
    logger.addHandler(error_handler)
    return logger


def load_config() -> dict:
    with open("conf_upload.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


class DriveClient:
    def __init__(self, config: dict, logger: logging.Logger) -> None:
        self.config = config
        self.logger = logger
        self.drive: GoogleDrive | None = None
        self.credentials_file = Path(config["google_drive"]["credentials_file"]).resolve()

    def ensure(self) -> GoogleDrive | None:
        if self.drive is not None:
            return self.drive
        try:
            gauth = GoogleAuth()
            gauth.LoadCredentialsFile(str(self.credentials_file))
            if gauth.credentials is None:
                self.logger.error("Aucun identifiant Google Drive. Exécuter l'authentification préalable.")
                return None
            if gauth.access_token_expired:
                gauth.Refresh()
            else:
                gauth.Authorize()
            gauth.SaveCredentialsFile(str(self.credentials_file))
            self.drive = GoogleDrive(gauth)
            self.logger.info("Client Google Drive initialisé.")
        except Exception:
            self.drive = None
            self.logger.exception("Échec de l'initialisation Google Drive.")
        return self.drive


def ensure_remote_folder(drive: GoogleDrive, parent_id: str | None, title: str) -> str:
    query = f"title='{title}' and mimeType='application/vnd.google-apps.folder'"
    if parent_id:
        query += f" and '{parent_id}' in parents"
    else:
        query += " and 'root' in parents"

    folders = drive.ListFile({"q": query}).GetList()
    if folders:
        return folders[0]["id"]

    metadata = {
        "title": title,
        "mimeType": "application/vnd.google-apps.folder",
    }
    if parent_id:
        metadata["parents"] = [{"id": parent_id}]
    else:
        metadata["parents"] = [{"id": "root"}]

    folder = drive.CreateFile(metadata)
    folder.Upload()
    return folder["id"]


def upload_file(
    drive: GoogleDrive,
    local_file: Path,
    local_base_path: Path,
    root_folder_name: str | None,
    root_folder_id: str | None,
    logger: logging.Logger,
) -> bool:
    try:
        relative_parts = list(local_file.relative_to(local_base_path).parent.parts)
    except ValueError:
        relative_parts = list(local_file.parent.parts[-5:])

    if root_folder_id:
        parent_id = root_folder_id
    else:
        parent_id = ensure_remote_folder(drive, None, root_folder_name or "CCTV_Archive")
    for part in relative_parts:
        parent_id = ensure_remote_folder(drive, parent_id, part)

    file_drive = drive.CreateFile({"title": local_file.name, "parents": [{"id": parent_id}]})
    file_drive.SetContentFile(str(local_file))
    file_drive.Upload()
    logger.info("Upload réussi: %s", local_file)
    return True


def main() -> None:
    config = load_config()

    logging_conf = config.get("logging", {})
    stdout_log = Path(logging_conf.get("stdout_log", "stdout.log"))
    error_log = Path(logging_conf.get("error_log", "errors.log"))
    logger = setup_logging(stdout_log, error_log)

    storage = config["storage"]
    queue_file = Path(storage["queue_file"]).resolve()
    local_base_path = Path(storage["local_base_path"]).resolve()
    local_base_path.mkdir(parents=True, exist_ok=True)
    delete_after_upload = bool(storage.get("delete_after_upload", False))

    scheduler = config.get("scheduler", {})
    idle_sleep_seconds = int(scheduler.get("idle_sleep_seconds", 5))
    retry_sleep_seconds = int(scheduler.get("retry_sleep_seconds", 60))

    google_conf = config["google_drive"]
    root_folder_id = google_conf.get("base_folder_id")
    root_folder_name = google_conf.get("base_folder_name", "CCTV_Archive")

    drive_client = DriveClient(config, logger)

    logger.info("Démarrage de l'uploader. Suppression après upload: %s", delete_after_upload)

    while True:
        entry = dequeue_entry(queue_file)
        if entry is None:
            time.sleep(idle_sleep_seconds)
            continue

        file_path = Path(entry)
        if not file_path.exists():
            logger.warning("Fichier introuvable, suppression de l'entrée: %s", entry)
            continue

        drive = drive_client.ensure()
        if drive is None:
            enqueue_entry(queue_file, entry)
            logger.error("Client Google Drive indisponible, nouvel essai dans %s s.", retry_sleep_seconds)
            time.sleep(retry_sleep_seconds)
            continue

        try:
            upload_success = upload_file(
                drive,
                file_path,
                local_base_path,
                root_folder_name,
                root_folder_id,
                logger,
            )
        except Exception:
            logger.exception("Échec de l'upload pour %s", file_path)
            enqueue_entry(queue_file, entry)
            time.sleep(retry_sleep_seconds)
            continue

        if upload_success and delete_after_upload:
            try:
                file_path.unlink()
                logger.info("Fichier local supprimé: %s", file_path)
            except FileNotFoundError:
                logger.warning("Fichier local déjà absent: %s", file_path)
            except Exception:
                logger.exception("Impossible de supprimer %s après upload.", file_path)


if __name__ == "__main__":
    main()
