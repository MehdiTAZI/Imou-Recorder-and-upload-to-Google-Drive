import datetime
import logging
import subprocess
import threading
import time
from pathlib import Path
from urllib.parse import quote

import yaml

import imageio_ffmpeg

from queue_utils import enqueue_entry


class MaxLevelFilter(logging.Filter):
    """Filter that only lets records up to a max level pass."""

    def __init__(self, max_level: int) -> None:
        super().__init__()
        self.max_level = max_level

    def filter(self, record: logging.LogRecord) -> bool:
        return record.levelno <= self.max_level


def setup_logging(stdout_path: Path, error_path: Path) -> logging.Logger:
    logger = logging.getLogger("record")
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
    with open("conf_record.yaml", "r", encoding="utf-8") as fh:
        return yaml.safe_load(fh)


def normalise_interval(config: dict, logger: logging.Logger) -> int:
    recording = config.setdefault("recording", {})
    interval = recording.get("interval_seconds")

    if interval is None:
        interval_minutes = recording.get("interval_minutes")
        if interval_minutes is None:
            logger.error("Intervalle d'enregistrement absent, utilisation de 60 secondes.")
            interval = 60
        else:
            interval = int(interval_minutes * 60)

    try:
        interval = int(interval)
    except Exception:
        logger.exception("Intervalle d'enregistrement invalide, utilisation de 60 secondes.")
        interval = 60

    if interval <= 0:
        logger.error("Intervalle d'enregistrement non positif, utilisation de 60 secondes.")
        interval = 60

    recording["interval_seconds"] = interval
    return interval


def get_overrun_seconds(config: dict, logger: logging.Logger) -> int:
    recording = config.setdefault("recording", {})
    overrun = recording.get("overrun_seconds", 2)
    try:
        overrun = int(overrun)
    except Exception:
        logger.exception("overrun_seconds invalide, utilisation de 2 secondes.")
        overrun = 2
    if overrun < 0:
        logger.warning("overrun_seconds négatif, utilisation de 0.")
        overrun = 0
    recording["overrun_seconds"] = overrun
    return overrun


def build_output_path(base_path: Path, cam_name: str, start: datetime.datetime, end: datetime.datetime) -> Path:
    folder = base_path / cam_name / f"{start.year}/{start.month:02}/{start.day:02}/{start.hour:02}"
    folder.mkdir(parents=True, exist_ok=True)
    filename = (
        f"{cam_name}_{start.strftime('%Y-%m-%d_%Hh%Mm%Ss')}"
        f"_à_{end.strftime('%Hh%Mm%Ss')}.mp4"
    )
    return folder / filename


def record_camera(
    cam: dict,
    nvr: dict,
    interval_seconds: int,
    overrun_seconds: int,
    encoding: dict | None,
    base_path: Path,
    logger: logging.Logger,
    scheduled_start: datetime.datetime,
) -> Path | None:
    start = scheduled_start.replace(microsecond=0)
    end = start + datetime.timedelta(seconds=interval_seconds)
    output_path = build_output_path(base_path, cam["name"], start, end)

    encoded_user = quote(str(nvr["username"]), safe="")
    encoded_pass = quote(str(nvr["password"]), safe="")
    rtsp_url = (
        f"rtsp://{encoded_user}:{encoded_pass}@{nvr['ip']}:{nvr['port']}/cam/realmonitor"
        f"?channel={cam['channel']}&subtype=0"
    )

    ffmpeg_path = imageio_ffmpeg.get_ffmpeg_exe()

    cmd = [
        ffmpeg_path,
        "-hide_banner",
        "-loglevel",
        "warning",
        "-rtsp_transport",
        nvr.get("transport", "tcp"),
        "-i",
        rtsp_url,
        "-t",
        str(interval_seconds + overrun_seconds),
        "-map",
        "0",
    ]

    if encoding:
        video_codec = encoding.get("video_codec", "copy")
        if encoding.get("lossless") and video_codec in {"libx265", "libx264"}:
            if video_codec == "libx265":
                cmd.extend(["-c:v", "libx265", "-preset", encoding.get("preset", "medium"), "-x265-params", "lossless=1"])
            else:
                cmd.extend(["-c:v", "libx264", "-preset", encoding.get("preset", "medium"), "-crf", "0"])
        elif video_codec == "ffv1":
            cmd.extend(["-c:v", "ffv1"])
        elif video_codec == "copy":
            cmd.extend(["-c:v", "copy"])
        else:
            cmd.extend(["-c:v", video_codec])
            if preset := encoding.get("preset"):
                cmd.extend(["-preset", str(preset)])
            if crf := encoding.get("crf"):
                cmd.extend(["-crf", str(crf)])
            if params := encoding.get("extra_args"):
                cmd.extend(params.split())
    else:
        cmd.extend(["-c:v", "copy"])

    if cam.get("enable_audio", True):
        if encoding and encoding.get("audio_codec"):
            audio_codec = encoding["audio_codec"]
            if audio_codec.lower() == "copy":
                cmd.extend(["-c:a", "copy"])
            else:
                cmd.extend(["-c:a", audio_codec])
        else:
            cmd.extend(["-c:a", "copy"])
    else:
        cmd.append("-an")

    cmd.extend(["-y", str(output_path)])

    logger.info("Enregistrement %s → %s", cam["name"], output_path)

    try:
        result = subprocess.run(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
        )
    except FileNotFoundError:
        logger.error("ffmpeg introuvable, impossible d'enregistrer %s.", cam["name"])
        return None
    except Exception:
        logger.exception("Erreur inattendue lors de l'enregistrement de %s.", cam["name"])
        return None

    if result.returncode != 0:
        stderr = result.stderr.decode("utf-8", errors="ignore")
        logger.error("ffmpeg a échoué pour %s (code %s)", cam["name"], result.returncode)
        logger.error("stderr: %s", stderr.strip())
        return None

    if not output_path.exists():
        logger.error("Enregistrement terminé mais fichier absent : %s", output_path)
        return None

    return output_path


def queue_recording(track_file: Path, file_path: Path, logger: logging.Logger) -> None:
    enqueue_entry(track_file, str(file_path.resolve()))
    logger.info("Fichier en attente d'upload: %s", file_path)


def camera_worker(
    cam: dict,
    nvr: dict,
    interval_seconds: int,
    overrun_seconds: int,
    encoding: dict | None,
    base_path: Path,
    track_file: Path,
    logger: logging.Logger,
) -> None:
    interval_delta = datetime.timedelta(seconds=interval_seconds)
    next_start = datetime.datetime.now()

    while True:
        now = datetime.datetime.now()
        wait_seconds = (next_start - now).total_seconds()
        if wait_seconds > 0:
            time.sleep(wait_seconds)

        scheduled_start = next_start
        file_path = record_camera(
            cam,
            nvr,
            interval_seconds,
            overrun_seconds,
            encoding,
            base_path,
            logger,
            scheduled_start,
        )
        if file_path:
            try:
                queue_recording(track_file, file_path, logger)
            except Exception:
                logger.exception("Impossible d'enregistrer %s dans la file d'upload.", file_path)
        else:
            logger.warning("Aucun fichier généré pour %s à %s", cam["name"], scheduled_start.isoformat(timespec="seconds"))

        next_start = scheduled_start + interval_delta
        if next_start < datetime.datetime.now():
            delay = (datetime.datetime.now() - next_start).total_seconds()
            logger.warning(
                "Retard détecté pour %s (%.1f s). Ajustement de l'horloge.",
                cam["name"],
                delay,
            )
            next_start = datetime.datetime.now()


def main() -> None:
    config = load_config()
    recording = config["recording"]
    storage = config["storage"]
    nvr = config["nvr"]

    stdout_log = Path(recording.get("stdout_log", "stdout.log"))
    error_log = Path(recording.get("error_log", "errors.log"))
    logger = setup_logging(stdout_log, error_log)

    interval_seconds = normalise_interval(config, logger)
    overrun_seconds = get_overrun_seconds(config, logger)
    encoding_config = recording.get("encoding")
    if isinstance(encoding_config, str) and encoding_config.lower() in {"", "none", "false"}:
        encoding_config = None
    elif not isinstance(encoding_config, dict):
        encoding_config = None

    base_path = Path(storage["local_base_path"]).resolve()
    base_path.mkdir(parents=True, exist_ok=True)
    track_file = Path(storage["queue_file"]).resolve()

    cameras = config.get("cameras", [])
    if not cameras:
        logger.error("Aucune caméra définie dans la configuration.")
        return

    logger.info("Intervalle d'enregistrement: %d s", interval_seconds)
    if encoding_config:
        logger.info("Encodage actif: %s", encoding_config)
    else:
        logger.info("Encodage désactivé (copie du flux vidéo).")
    logger.info("Stockage local: %s", base_path)
    logger.info("File d'upload: %s", track_file)
    logger.info("Initialisation de l'enregistreur pour %d caméras.", len(cameras))

    threads: list[threading.Thread] = []
    for cam in cameras:
        worker = threading.Thread(
            target=camera_worker,
            name=f"camera-{cam['name']}",
            args=(cam, nvr, interval_seconds, overrun_seconds, encoding_config, base_path, track_file, logger),
            daemon=True,
        )
        worker.start()
        threads.append(worker)
        logger.info("Thread démarré pour %s.", cam["name"])

    # Boucle principale : garde le programme vivant.
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        logger.info("Arrêt demandé par l'utilisateur. Les threads vont s'arrêter.")
        for thread in threads:
            thread.join(timeout=1)


if __name__ == "__main__":
    main()
