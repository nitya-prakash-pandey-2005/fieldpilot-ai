"""Command-line interface.

Design principle: the CLI is a first-class consumer of the same library the API
uses, not a thin demo. Anything you can do over HTTP you can do here, and the
CLI is the *preferred* path for long videos because it streams results to disk
instead of accumulating them in memory.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from typing import Annotated, Any

import typer
from rich.console import Console
from rich.progress import BarColumn, Progress, SpinnerColumn, TextColumn, TimeRemainingColumn
from rich.table import Table

from measurecv import __version__
from measurecv.core.config import AppConfig, load_config
from measurecv.core.exceptions import MeasureCVError
from measurecv.core.logging import configure_logging, get_logger

log = get_logger(__name__)
console = Console()

app = typer.Typer(
    name="measurecv",
    help="Metric object measurement from RGB images, video and live cameras.",
    no_args_is_help=True,
    add_completion=True,
)

ConfigOption = Annotated[
    Path | None, typer.Option("--config", "-c", help="YAML configuration file")
]
DeviceOption = Annotated[str | None, typer.Option("--device", help="auto | cuda | mps | cpu")]
VerboseOption = Annotated[bool, typer.Option("--verbose", "-v", help="Debug logging")]


def _build_config(
    path: Path | None, device: str | None, verbose: bool, synthetic: bool = False
) -> AppConfig:
    overrides: dict[str, Any] = {}
    if device:
        overrides["runtime"] = {"device": device}
    if verbose:
        overrides["log_level"] = "DEBUG"

    config = load_config(path, **overrides)
    if synthetic:
        config = config.synthetic()
    configure_logging(config.log_level, json_output=config.log_json)
    return config


def _fail(message: str, code: int = 1) -> None:
    console.print(f"[bold red]error:[/bold red] {message}")
    raise typer.Exit(code)


@app.callback()
def main() -> None:
    """Measurecv -- RT-DETR + SAM 2 + Metric3D metric measurement."""


@app.command()
def version() -> None:
    """Print version and environment details."""
    from measurecv.core.device import resolve_device, torch_available

    console.print(f"[bold]measurecv[/bold] {__version__}")
    console.print(f"python    {sys.version.split()[0]}")
    console.print(
        f"torch     {'available' if torch_available() else '[yellow]not installed[/yellow]'}"
    )
    ctx = resolve_device()
    console.print(f"device    {ctx.device} ({ctx.name}), dtype {ctx.dtype_name}")


@app.command()
def measure(
    source: Annotated[Path, typer.Argument(help="Image file or directory of images")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="JSON output path")] = None,
    annotate: Annotated[
        Path | None, typer.Option("--annotate", "-a", help="Save annotated image")
    ] = None,
    depth_map: Annotated[
        Path | None, typer.Option("--depth", help="Save colourised depth map")
    ] = None,
    point_cloud: Annotated[
        Path | None, typer.Option("--ply", help="Save the scene point cloud")
    ] = None,
    calibration: Annotated[
        Path | None, typer.Option("--calibration", help="Intrinsics JSON")
    ] = None,
    classes: Annotated[
        str | None, typer.Option("--classes", help="Comma-separated class filter")
    ] = None,
    threshold: Annotated[float | None, typer.Option("--threshold", "-t", min=0.0, max=1.0)] = None,
    config: ConfigOption = None,
    device: DeviceOption = None,
    dry_run: Annotated[
        bool, typer.Option("--dry-run", help="Use synthetic backends (no weights)")
    ] = False,
    verbose: VerboseOption = False,
) -> None:
    """Measure objects in a still image."""
    cfg = _build_config(config, device, verbose, synthetic=dry_run)
    if calibration:
        cfg.calibration.profile = calibration
    if classes:
        cfg.detection.class_whitelist = [c.strip() for c in classes.split(",") if c.strip()]
    if threshold is not None:
        cfg.detection.score_threshold = threshold

    from measurecv.pipeline.pipeline import MeasurementPipeline
    from measurecv.pipeline.sources import open_source

    pipeline = MeasurementPipeline(cfg)

    try:
        frames = open_source(source)
    except MeasureCVError as exc:
        _fail(exc.message)
        return

    scenes = []
    with frames:
        for frame in frames:
            with console.status(f"measuring {Path(frame.source_id).name}..."):
                try:
                    artifacts = pipeline.measure_frame_full(frame, track=False)
                except MeasureCVError as exc:
                    _fail(f"{exc.code}: {exc.message}")
                    return

            scene = artifacts.scene
            scenes.append(scene)
            _print_scene(scene)

            if annotate:
                _save_annotated(annotate, artifacts, len(scenes) > 1, len(scenes) - 1)
            if depth_map:
                _save_depth(depth_map, artifacts, len(scenes) > 1, len(scenes) - 1)
            if point_cloud:
                _save_cloud(point_cloud, artifacts)

    if output:
        from measurecv.export.serializers import write_json

        if len(scenes) == 1:
            write_json(output, scenes[0])
        else:
            output.parent.mkdir(parents=True, exist_ok=True)
            output.write_text(json.dumps([s.to_dict() for s in scenes], indent=2), encoding="utf-8")
        console.print(f"[green]saved[/green] {output}")


@app.command()
def video(
    source: Annotated[str, typer.Argument(help="Video file path")],
    output: Annotated[Path | None, typer.Option("--output", "-o", help="NDJSON output")] = None,
    csv: Annotated[
        Path | None, typer.Option("--csv", help="CSV output, one row per object")
    ] = None,
    render: Annotated[Path | None, typer.Option("--render", help="Annotated video output")] = None,
    max_frames: Annotated[int | None, typer.Option("--max-frames", min=1)] = None,
    stride: Annotated[int, typer.Option("--stride", min=1, help="Process every Nth frame")] = 1,
    calibration: Annotated[Path | None, typer.Option("--calibration")] = None,
    config: ConfigOption = None,
    device: DeviceOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    verbose: VerboseOption = False,
) -> None:
    """Measure a video file with tracking and temporal fusion."""
    cfg = _build_config(config, device, verbose, synthetic=dry_run)
    if calibration:
        cfg.calibration.profile = calibration

    import cv2

    from measurecv.export.serializers import NdjsonWriter, summarise, write_csv
    from measurecv.pipeline.pipeline import MeasurementPipeline
    from measurecv.pipeline.sources import open_source
    from measurecv.viz.annotate import AnnotationStyle, draw_scene

    pipeline = MeasurementPipeline(cfg)

    try:
        frames = open_source(source, stride=stride, max_frames=max_frames)
    except MeasureCVError as exc:
        _fail(exc.message)
        return

    total = frames.frame_count
    writer = NdjsonWriter(output) if output else None
    video_writer: Any = None
    scenes = []
    started = time.perf_counter()

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TextColumn("{task.completed}/{task.total}" if total > 0 else "{task.completed}"),
            TimeRemainingColumn(),
            console=console,
        ) as progress:
            task = progress.add_task("measuring", total=total if total > 0 else None)

            for scene, frame in pipeline.process_video(frames):
                if writer:
                    writer.write(scene)
                if csv:
                    scenes.append(scene)

                if render:
                    artifacts = None
                    annotated = draw_scene(
                        frame.image, scene, style=AnnotationStyle(show_volume=True)
                    )
                    if video_writer is None:
                        render.parent.mkdir(parents=True, exist_ok=True)
                        height, width = annotated.shape[:2]
                        video_writer = cv2.VideoWriter(
                            str(render),
                            cv2.VideoWriter_fourcc(*"mp4v"),
                            max(1.0, frames.fps / stride),
                            (width, height),
                        )
                        if not video_writer.isOpened():
                            console.print("[yellow]warning:[/yellow] could not open video writer")
                            video_writer = None
                    if video_writer is not None:
                        video_writer.write(cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))
                    del artifacts

                progress.advance(task)
    finally:
        if writer:
            writer.close()
        if video_writer is not None:
            video_writer.release()
        frames.close()

    if csv and scenes:
        write_csv(csv, scenes)
        console.print(f"[green]saved[/green] {csv}")

    elapsed = time.perf_counter() - started
    stats = pipeline.stats()
    processed = stats["frames_processed"]
    console.print()
    console.print(
        f"[bold green]done[/bold green] {processed} frames in {elapsed:.1f}s "
        f"({processed / elapsed:.2f} fps)"
    )
    if scenes:
        console.print(json.dumps(summarise(scenes), indent=2))
    if output:
        console.print(f"[green]saved[/green] {output}")
    if render:
        console.print(f"[green]saved[/green] {render}")


@app.command()
def stream(
    source: Annotated[str, typer.Argument(help="Camera index, rtsp:// or http:// URL")] = "0",
    display: Annotated[
        bool, typer.Option("--display/--no-display", help="Show a preview window")
    ] = True,
    output: Annotated[Path | None, typer.Option("--output", "-o", help="NDJSON output")] = None,
    config: ConfigOption = None,
    device: DeviceOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    verbose: VerboseOption = False,
) -> None:
    """Measure a live camera or network stream. Press q to stop.

    Display and measurement run at independent rates: the preview stays at
    camera framerate while measurement proceeds as fast as the hardware
    allows, with the newest result overlaid. On CPU that means a smooth
    picture with numbers refreshing every few seconds, rather than a preview
    that freezes between measurements.
    """
    cfg = _build_config(config, device, verbose, synthetic=dry_run)

    import cv2

    from measurecv.export.serializers import NdjsonWriter
    from measurecv.pipeline.live import LiveSession, compose_live_frame
    from measurecv.pipeline.pipeline import MeasurementPipeline
    from measurecv.pipeline.sources import open_source
    from measurecv.viz.annotate import AnnotationStyle

    pipeline = MeasurementPipeline(cfg)

    try:
        frames = open_source(source)
    except MeasureCVError as exc:
        _fail(exc.message)
        return

    # Warm the models on a background thread so the window opens immediately.
    # Loading takes ~20s on CPU, and a blank terminal for that long is
    # indistinguishable from a hang. The measurement worker blocks on the same
    # lazy loader, so it simply starts producing once the weights are in.
    import threading

    threading.Thread(target=pipeline.warmup, name="warmup", daemon=True).start()
    console.print("[dim]loading models in the background; preview starts now[/dim]")

    writer = NdjsonWriter(output) if output else None
    style = AnnotationStyle(show_volume=True)
    last_written = -1

    console.print(
        f"[bold]streaming[/bold] from {source} -- "
        + ("press q in the window to stop" if display else "press Ctrl+C to stop")
    )

    session = LiveSession(pipeline, frames, track=True)
    try:
        with session:
            for frame, result in session.stream():
                if writer and result is not None and result.frame_index != last_written:
                    writer.write(result.scene)
                    last_written = result.frame_index

                if display:
                    canvas = compose_live_frame(frame, result, session.stats, style=style)
                    cv2.imshow("measurecv", cv2.cvtColor(canvas, cv2.COLOR_RGB2BGR))
                    if cv2.waitKey(1) & 0xFF == ord("q"):
                        break
    except KeyboardInterrupt:
        console.print("\n[yellow]interrupted[/yellow]")
    finally:
        if writer:
            writer.close()
        if display:
            cv2.destroyAllWindows()

    table = Table(title="Live session", show_header=False)
    for key, value in session.stats.to_dict().items():
        table.add_row(key.replace("_", " "), str(value))
    console.print(table)


@app.command()
def calibrate(
    images: Annotated[Path, typer.Argument(help="Directory of calibration target photos")],
    output: Annotated[
        Path, typer.Option("--output", "-o", help="Where to write intrinsics")
    ] = Path("calibration.json"),
    board: Annotated[str, typer.Option("--board", help="Inner corners as COLSxROWS")] = "9x6",
    square_size: Annotated[
        float, typer.Option("--square-size", help="Square size in metres")
    ] = 0.025,
    board_type: Annotated[str, typer.Option("--type", help="chessboard | charuco")] = "chessboard",
    marker_size: Annotated[
        float, typer.Option("--marker-size", help="ChArUco marker size, metres")
    ] = 0.018,
    min_views: Annotated[int, typer.Option("--min-views", min=3)] = 8,
    max_rms: Annotated[
        float, typer.Option("--max-rms", help="Reject above this reprojection RMS")
    ] = 1.0,
    verbose: VerboseOption = False,
) -> None:
    """Calibrate a camera from photos of a chessboard or ChArUco target.

    Tips that dominate the result:
    measure the printed square, vary the board's orientation strongly between
    shots, and include views where the board reaches the image corners.
    """
    configure_logging("DEBUG" if verbose else "INFO")

    from measurecv.calibration.board import calibrate_from_paths

    try:
        cols, rows = (int(v) for v in board.lower().split("x"))
    except ValueError:
        _fail(f"--board must look like 9x6, got {board!r}")
        return

    suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".tif", ".tiff", ".webp"}
    paths = (
        sorted(p for p in images.iterdir() if p.suffix.lower() in suffixes)
        if images.is_dir()
        else [images]
    )
    if not paths:
        _fail(f"no images found in {images}")
        return

    console.print(
        f"calibrating from {len(paths)} images, {board} board, {square_size * 1000:.1f}mm squares"
    )

    try:
        result = calibrate_from_paths(
            paths,
            board_shape=(cols, rows),
            square_size_m=square_size,
            board_type=board_type,
            marker_size_m=marker_size,
            min_views=min_views,
            max_rms_error_px=max_rms,
        )
    except MeasureCVError as exc:
        _fail(f"{exc.message}")
        return

    result.intrinsics.save(output)

    table = Table(title="Calibration result", show_header=False)
    table.add_row("fx, fy", f"{result.intrinsics.fx:.2f}, {result.intrinsics.fy:.2f} px")
    table.add_row("cx, cy", f"{result.intrinsics.cx:.2f}, {result.intrinsics.cy:.2f} px")
    table.add_row("FOV", f"{result.intrinsics.hfov_deg:.1f}° x {result.intrinsics.vfov_deg:.1f}°")
    table.add_row("distortion", ", ".join(f"{v:.5f}" for v in result.intrinsics.distortion))
    table.add_row("RMS error", f"{result.rms_error:.4f} px")
    table.add_row("views used", f"{len(result.accepted_views)} / {len(paths)}")
    table.add_row("coverage", f"{result.coverage:.1%}")
    table.add_row("focal uncertainty", f"{result.intrinsics.focal_uncertainty:.2%}")
    console.print(table)

    if result.coverage < 0.4:
        console.print(
            "[yellow]warning:[/yellow] low image coverage -- distortion coefficients are "
            "extrapolating. Add views with the board near the image corners."
        )
    if result.rejected_views:
        console.print(f"[dim]rejected {len(result.rejected_views)} views[/dim]")

    console.print(f"[green]saved[/green] {output}")


@app.command()
def serve(
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
    reload: Annotated[
        bool, typer.Option("--reload", help="Auto-reload (development only)")
    ] = False,
    config: ConfigOption = None,
    device: DeviceOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
    verbose: VerboseOption = False,
) -> None:
    """Start the HTTP API server."""
    cfg = _build_config(config, device, verbose, synthetic=dry_run)
    if host:
        cfg.api.host = host
    if port:
        cfg.api.port = port

    try:
        import uvicorn
    except ImportError:
        _fail("the API needs the 'api' extra: pip install 'measurecv[api]'")
        return

    from measurecv.api.app import create_app

    console.print(
        f"[bold]measurecv {__version__}[/bold] serving on http://{cfg.api.host}:{cfg.api.port}"
    )
    if cfg.api.enable_docs:
        console.print(f"docs: http://{cfg.api.host}:{cfg.api.port}/docs")

    uvicorn.run(
        create_app(cfg),
        host=cfg.api.host,
        port=cfg.api.port,
        reload=reload,
        access_log=False,
    )


@app.command()
def verify(
    images: Annotated[
        Path | None, typer.Argument(help="Optional folder of real photos to also run")
    ] = None,
    output: Annotated[Path, typer.Option("--output", "-o", help="Where to write artefacts")] = Path(
        "verification"
    ),
    config: ConfigOption = None,
    device: DeviceOption = None,
    skip_models: Annotated[
        bool, typer.Option("--skip-models", help="Only run the weight-free geometry checks")
    ] = False,
) -> None:
    """Check the install is correct by measuring things with known answers.

    Two independent levels of evidence:

    **Analytic** -- synthetic scenes whose true metric size follows from
    pinhole geometry, so the measured value can be compared against a closed
    form. These need no weights and no GPU, and they are what actually proves
    the geometry is right.

    **End-to-end** -- the real models on real photos. There is no ground truth
    here, so this checks that the stack runs and that the numbers are
    physically plausible; the analytic level is what checks correctness.
    """
    cfg = _build_config(config, device, False)
    output.mkdir(parents=True, exist_ok=True)

    console.print("\n[bold]1. Analytic checks[/bold] (closed-form ground truth, no weights)\n")
    analytic = _run_analytic_checks()

    table = Table(show_header=True)
    table.add_column("check")
    table.add_column("expected", justify="right")
    table.add_column("measured", justify="right")
    table.add_column("error", justify="right")
    table.add_column("", justify="center")

    failures = 0
    for name, expected, measured, unit, tolerance in analytic:
        error = abs(measured - expected)
        relative = error / abs(expected) if expected else 0.0
        passed = error <= tolerance
        failures += 0 if passed else 1
        table.add_row(
            name,
            f"{expected:.4f} {unit}",
            f"{measured:.4f} {unit}",
            f"{relative:.2%}",
            "[green]PASS[/green]" if passed else "[red]FAIL[/red]",
        )
    console.print(table)

    if skip_models:
        console.print(
            f"\n[bold]{'PASS' if failures == 0 else 'FAIL'}[/bold] "
            f"{len(analytic) - failures}/{len(analytic)} analytic checks"
        )
        raise typer.Exit(1 if failures else 0)

    console.print("\n[bold]2. End-to-end[/bold] (real models; plausibility, not ground truth)\n")

    import cv2

    from measurecv.core.types import Frame
    from measurecv.pipeline.pipeline import MeasurementPipeline
    from measurecv.pipeline.sources import read_image
    from measurecv.viz.annotate import AnnotationStyle, draw_depth_map, draw_scene

    pipeline = MeasurementPipeline(cfg)

    suffixes = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
    paths = (
        sorted(p for p in images.iterdir() if p.suffix.lower() in suffixes)
        if images and images.is_dir()
        else ([images] if images else [])
    )
    if not paths:
        console.print("[dim]no photos supplied; skipping (pass a folder to include them)[/dim]")
        raise typer.Exit(1 if failures else 0)

    summary: list[dict[str, Any]] = []
    for path in paths:
        with console.status(f"measuring {path.name}..."):
            try:
                artifacts = pipeline.measure_frame_full(
                    Frame(image=read_image(path), source_id=str(path)), track=False
                )
            except MeasureCVError as exc:
                console.print(f"  [red]FAIL[/red] {path.name}: {exc.message}")
                failures += 1
                continue

        scene = artifacts.scene
        annotated = draw_scene(
            artifacts.image,
            scene,
            masks=[m.mask for m in artifacts.masks],
            intrinsics=artifacts.intrinsics,
            style=AnnotationStyle(show_volume=True),
        )
        cv2.imwrite(
            str(output / f"{path.stem}_measured.jpg"),
            cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR),
            [int(cv2.IMWRITE_JPEG_QUALITY), 88],
        )
        cv2.imwrite(
            str(output / f"{path.stem}_depth.jpg"),
            cv2.cvtColor(draw_depth_map(artifacts.depth_map.depth), cv2.COLOR_RGB2BGR),
            [int(cv2.IMWRITE_JPEG_QUALITY), 88],
        )

        measured = [o for o in scene.objects if o.dimensions is not None]
        console.print(
            f"  [green]OK[/green] {path.name:<24} {len(measured)}/{len(scene.objects)} measured"
            f"  {scene.timings_ms.get('total', 0):.0f} ms"
        )
        for obj in measured[:4]:
            d = obj.dimensions
            console.print(
                f"       [dim]{obj.detection.label:<14}"
                f"{d.length.value:.3f} x {d.width.value:.3f} x {d.height.value:.3f} m"
                f"   {obj.confidence:.0%}[/dim]"
            )
        summary.append(
            {
                "image": path.name,
                "objects": len(scene.objects),
                "measured": len(measured),
                "calibration": scene.calibration_source,
                "total_ms": round(scene.timings_ms.get("total", 0.0), 1),
                "results": [
                    {
                        "label": o.detection.label,
                        "dimensions_m": [
                            round(o.dimensions.length.value, 4),
                            round(o.dimensions.width.value, 4),
                            round(o.dimensions.height.value, 4),
                        ],
                        "relative_error": round(
                            max(
                                o.dimensions.length,
                                o.dimensions.width,
                                o.dimensions.height,
                                key=lambda m: m.value,
                            ).relative_error,
                            4,
                        ),
                        "distance_m": round(o.distance.value, 3) if o.distance else None,
                        "confidence": round(o.confidence, 3),
                        "warnings": o.warnings,
                    }
                    for o in measured
                ],
            }
        )

    (output / "verification.json").write_text(
        json.dumps({"analytic": [list(a) for a in analytic], "end_to_end": summary}, indent=2),
        encoding="utf-8",
    )

    console.print(f"\nartefacts written to [bold]{output}[/bold]")
    console.print(
        f"\n[bold]{'PASS' if failures == 0 else 'FAIL'}[/bold] "
        f"{len(analytic) - failures}/{len(analytic)} analytic checks, "
        f"{len(summary)}/{len(paths)} images processed"
    )
    raise typer.Exit(1 if failures else 0)


def _run_analytic_checks() -> list[tuple[str, float, float, str, float]]:
    """Measure synthetic scenes whose true size is known in closed form.

    Returns ``(name, expected, measured, unit, tolerance)`` rows.
    """
    import numpy as np

    from measurecv.calibration.intrinsics import intrinsics_from_fov
    from measurecv.core.config import MeasurementConfig
    from measurecv.core.types import DepthMap, Detection, InstanceMask, Plane, PointCloud
    from measurecv.geometry.hull import closed_hull_volume
    from measurecv.geometry.obb import fit_ground_aligned_box, min_area_rect
    from measurecv.geometry.plane import SupportFrame, estimate_support_plane
    from measurecv.measurement.engine import MeasurementEngine

    rng = np.random.default_rng(20240611)
    rows: list[tuple[str, float, float, str, float]] = []

    # -- minimum-area rectangle on a rotated rectangle ----------------------
    w_true, h_true = 0.400, 0.250
    theta = np.deg2rad(31.0)
    rot = np.array([[np.cos(theta), -np.sin(theta)], [np.sin(theta), np.cos(theta)]])
    pts = rng.uniform(-0.5, 0.5, size=(4000, 2)) * np.array([w_true, h_true])
    rect = min_area_rect(pts @ rot.T + np.array([1.3, -0.7]))
    rows.append(("rotated rectangle, long side", w_true, float(rect.extents[0]), "m", 0.006))
    rows.append(("rotated rectangle, short side", h_true, float(rect.extents[1]), "m", 0.006))

    # -- support-plane recovery --------------------------------------------
    floor = rng.uniform(-2, 2, size=(4000, 3))
    floor[:, 1] = 1.4
    floor[:, 2] = np.abs(floor[:, 2]) + 1.0
    plane = estimate_support_plane(PointCloud(floor))
    rows.append(("ground plane height", 1.4, abs(plane.d) if plane else 0.0, "m", 0.02))

    # -- ground-aligned box on a cuboid ------------------------------------
    dims_true = (0.300, 0.200, 0.450)
    frame = SupportFrame.from_plane(Plane(normal=np.array([0.0, -1.0, 0.0]), d=1.4))
    u = rng.random((8000, 3))
    face = rng.integers(0, 3, 8000)
    u[face == 0, 0] = np.round(u[face == 0, 0])
    u[face == 1, 1] = np.round(u[face == 1, 1])
    u[face == 2, 2] = 1.0
    world = (u - np.array([0.5, 0.5, 0.0])) * np.array(dims_true)
    yaw = np.deg2rad(20.0)
    rz = np.array([[np.cos(yaw), -np.sin(yaw), 0], [np.sin(yaw), np.cos(yaw), 0], [0, 0, 1]])
    cuboid = frame.to_camera(world @ rz.T)
    box = fit_ground_aligned_box(cuboid, frame.plane, percentile=0.5)
    for label, expected, got in zip(
        ("cuboid length", "cuboid width", "cuboid height"), dims_true, box.extents, strict=True
    ):
        rows.append((label, expected, float(got), "m", 0.010))

    volume, _ = closed_hull_volume(cuboid, frame.plane, percentile=1.0)
    rows.append(
        (
            "cuboid volume",
            float(np.prod(dims_true)),
            volume,
            "m^3",
            float(np.prod(dims_true)) * 0.12,
        )
    )

    # -- full back-projection from a rendered depth map --------------------
    width, height, depth_z = 640, 480, 2.0
    plate_w, plate_h = 0.500, 0.300
    k = intrinsics_from_fov(width, height, 60.0)
    depth = np.full((height, width), 40.0, np.float32)
    uu, vv = np.meshgrid(np.arange(width), np.arange(height))
    x = (uu - k.cx) * depth_z / k.fx
    y = (vv - k.cy) * depth_z / k.fy
    mask = (np.abs(x) <= plate_w / 2) & (np.abs(y) <= plate_h / 2)
    depth[mask] = depth_z

    engine = MeasurementEngine(MeasurementConfig(min_points=100, estimate_ground_plane=False))
    detection = Detection(bbox=InstanceMask(mask).bbox(), score=0.9, label_id=1, label="plate")
    scene = engine.measure_scene(
        [detection], [InstanceMask(mask)], DepthMap(depth, scale_uncertainty=0.05), k
    )
    # A failure here means the engine declined to measure a scene it certainly
    # should be able to. Report it as failed checks rather than raising an
    # AttributeError, so `verify` still prints a usable table.
    obj = scene.objects[0] if scene.objects else None
    if obj is None or obj.dimensions is None or obj.distance is None:
        rows.append(("plate width (full pipeline)", plate_w, 0.0, "m", 0.008))
        rows.append(("plate height (full pipeline)", plate_h, 0.0, "m", 0.008))
        rows.append(("plate range (full pipeline)", depth_z, 0.0, "m", 0.06))
        return rows

    d = obj.dimensions
    extents = sorted([d.length.value, d.width.value, d.height.value], reverse=True)
    rows.append(("plate width (full pipeline)", plate_w, extents[0], "m", 0.008))
    rows.append(("plate height (full pipeline)", plate_h, extents[1], "m", 0.008))
    rows.append(("plate range (full pipeline)", depth_z, obj.distance.value, "m", 0.06))

    return rows


@app.command()
def benchmark(
    source: Annotated[
        Path | None, typer.Argument(help="Image to benchmark; synthetic if omitted")
    ] = None,
    iterations: Annotated[int, typer.Option("--iterations", "-n", min=1)] = 20,
    warmup: Annotated[int, typer.Option("--warmup", min=0)] = 3,
    config: ConfigOption = None,
    device: DeviceOption = None,
    dry_run: Annotated[bool, typer.Option("--dry-run")] = False,
) -> None:
    """Measure per-stage latency.

    Reports a per-stage breakdown rather than a single number, because the
    optimisation you should reach for differs completely depending on whether
    detection, segmentation or depth dominates.
    """
    import numpy as np

    cfg = _build_config(config, device, False, synthetic=dry_run)

    from measurecv.core.types import Frame
    from measurecv.pipeline.pipeline import MeasurementPipeline
    from measurecv.pipeline.sources import read_image

    pipeline = MeasurementPipeline(cfg)

    if source:
        image = read_image(source)
    else:
        rng = np.random.default_rng(0)
        image = np.full((720, 1280, 3), 100, dtype=np.uint8)
        for i in range(4):
            y, x = 200 + i * 90, 150 + i * 220
            image[y : y + 140, x : x + 160] = rng.integers(60, 240, 3, dtype=np.uint8)

    console.print(f"warming up ({warmup} iterations)...")
    for _ in range(warmup):
        pipeline.measure_frame(Frame(image=image), track=False)

    stage_times: dict[str, list[float]] = {}
    totals: list[float] = []

    with Progress(
        SpinnerColumn(), TextColumn("benchmarking"), BarColumn(), console=console
    ) as progress:
        task = progress.add_task("run", total=iterations)
        for _ in range(iterations):
            started = time.perf_counter()
            scene = pipeline.measure_frame(Frame(image=image), track=False)
            totals.append((time.perf_counter() - started) * 1000.0)
            for stage, value in scene.timings_ms.items():
                stage_times.setdefault(stage, []).append(value)
            progress.advance(task)

    table = Table(title=f"Latency over {iterations} iterations ({image.shape[1]}x{image.shape[0]})")
    table.add_column("stage")
    table.add_column("mean ms", justify="right")
    table.add_column("p50", justify="right")
    table.add_column("p95", justify="right")
    table.add_column("share", justify="right")

    total_mean = float(np.mean(totals))
    for stage, values in sorted(stage_times.items(), key=lambda kv: -float(np.mean(kv[1]))):
        if stage == "total":
            continue
        mean = float(np.mean(values))
        table.add_row(
            stage,
            f"{mean:.1f}",
            f"{float(np.percentile(values, 50)):.1f}",
            f"{float(np.percentile(values, 95)):.1f}",
            f"{mean / total_mean:.0%}",
        )
    table.add_row(
        "[bold]total[/bold]",
        f"[bold]{total_mean:.1f}[/bold]",
        f"{float(np.percentile(totals, 50)):.1f}",
        f"{float(np.percentile(totals, 95)):.1f}",
        "100%",
    )
    console.print(table)
    console.print(f"throughput: [bold]{1000.0 / total_mean:.2f} fps[/bold]")


# ---------------------------------------------------------------------------
# helpers
# ---------------------------------------------------------------------------
def _print_scene(scene: Any) -> None:
    """Render a scene as a table."""
    if not scene.objects:
        console.print("[yellow]no objects detected[/yellow]")
        return

    table = Table(
        title=f"{len(scene.objects)} object(s) -- calibration: {scene.calibration_source}"
    )
    table.add_column("#", justify="right")
    table.add_column("label")
    table.add_column("L x W x H (m)")
    table.add_column("volume", justify="right")
    table.add_column("distance", justify="right")
    table.add_column("conf", justify="right")

    for index, obj in enumerate(scene.objects):
        if obj.dimensions:
            d = obj.dimensions
            dims = f"{d.length.value:.3f} x {d.width.value:.3f} x {d.height.value:.3f}"
            # Quote the relative error of the *largest* dimension, not the
            # worst one. A near-degenerate axis (a flat object's thickness) has
            # a relative error that tends to infinity as its value tends to
            # zero, so "worst" reports a meaningless five-digit percentage
            # instead of the accuracy of the number the user actually cares
            # about. The nearly-planar warning already flags the thin axis.
            principal = max(d.length, d.width, d.height, key=lambda m: m.value)
            dims += f"  ±{principal.relative_error:.0%}"
        else:
            dims = "[dim]not measurable[/dim]"

        volume = f"{obj.volume.value * 1000:.1f} L" if obj.volume else "-"
        distance = f"{obj.distance.value:.2f} m" if obj.distance else "-"
        colour = "green" if obj.confidence > 0.7 else "yellow" if obj.confidence > 0.4 else "red"

        table.add_row(
            str(index),
            obj.detection.label,
            dims,
            volume,
            distance,
            f"[{colour}]{obj.confidence:.0%}[/{colour}]",
        )

    console.print(table)

    if scene.calibration_source == "assumed_fov":
        console.print(
            "[yellow]note:[/yellow] no calibration -- absolute scale is uncertain to ~15%. "
            "Run [bold]measurecv calibrate[/bold] for metrology-grade results."
        )

    warned = {w for obj in scene.objects for w in obj.warnings} | set(scene.warnings)
    for warning in sorted(warned):
        console.print(f"  [dim]! {warning}[/dim]")


def _save_annotated(path: Path, artifacts: Any, multi: bool, index: int) -> None:
    import cv2

    from measurecv.viz.annotate import AnnotationStyle, draw_scene

    target = path if not multi else path.with_stem(f"{path.stem}_{index:04d}")
    annotated = draw_scene(
        artifacts.image,
        artifacts.scene,
        masks=[m.mask for m in artifacts.masks],
        intrinsics=artifacts.intrinsics,
        style=AnnotationStyle(show_volume=True),
    )
    target.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(target), cv2.cvtColor(annotated, cv2.COLOR_RGB2BGR))
    console.print(f"[green]saved[/green] {target}")


def _save_depth(path: Path, artifacts: Any, multi: bool, index: int) -> None:
    import cv2

    from measurecv.viz.annotate import draw_depth_map

    target = path if not multi else path.with_stem(f"{path.stem}_{index:04d}")
    target.parent.mkdir(parents=True, exist_ok=True)
    coloured = draw_depth_map(artifacts.depth_map.depth)
    cv2.imwrite(str(target), cv2.cvtColor(coloured, cv2.COLOR_RGB2BGR))
    console.print(f"[green]saved[/green] {target}")


def _save_cloud(path: Path, artifacts: Any) -> None:
    from measurecv.geometry.backproject import backproject_depth_map
    from measurecv.viz.export3d import write_ply

    cloud = backproject_depth_map(
        artifacts.depth_map,
        artifacts.intrinsics,
        stride=2,
        image=artifacts.image,
        max_points=2_000_000,
    )
    write_ply(path, cloud)
    console.print(f"[green]saved[/green] {path} ({len(cloud):,} points)")


if __name__ == "__main__":  # pragma: no cover
    app()
