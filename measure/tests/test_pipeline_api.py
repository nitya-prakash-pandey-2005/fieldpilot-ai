"""End-to-end pipeline, export, visualisation and HTTP API tests."""

from __future__ import annotations

import json

import numpy as np
import pytest

from measurecv.core.types import Frame
from measurecv.export.serializers import (
    NdjsonWriter,
    decode_rle,
    encode_rle,
    scene_to_coco,
    scene_to_csv,
    scene_to_json,
    summarise,
    write_csv,
    write_json,
)
from measurecv.pipeline.sources import ImageSource, decode_image_bytes, open_source, read_image
from measurecv.viz.annotate import AnnotationStyle, draw_depth_map, draw_scene, track_color
from measurecv.viz.export3d import read_ply_header, write_obb_obj, write_ply


class TestPipelineEndToEnd:
    def test_recovers_analytic_dimensions(self, pipeline, billboard_scene) -> None:
        """The headline end-to-end guarantee.

        The synthetic scene's true metric size follows from pinhole geometry,
        so this asserts the whole chain -- detection, segmentation, depth,
        plane fitting, filtering, bias correction -- against closed-form truth.
        """
        scene = pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=False)

        assert len(scene.objects) == 1
        obj = scene.objects[0]
        assert obj.dimensions is not None

        assert obj.dimensions.length.value == pytest.approx(
            billboard_scene["true_width_m"], rel=0.05
        )
        assert obj.dimensions.height.value == pytest.approx(
            billboard_scene["true_height_m"], rel=0.05
        )

    def test_finds_the_ground_plane(self, pipeline, billboard_scene) -> None:
        scene = pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=False)

        assert scene.ground_plane is not None
        assert abs(float(scene.ground_plane.normal @ np.array([0.0, -1.0, 0.0]))) > 0.98

    def test_reports_uncertainty_and_provenance(self, pipeline, billboard_scene) -> None:
        scene = pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=False)
        obj = scene.objects[0]

        assert obj.dimensions.length.sigma > 0
        assert scene.calibration_source == "assumed_fov"
        assert any("assumed" in w for w in obj.warnings)

    def test_empty_scene_produces_no_objects(self, pipeline) -> None:
        blank = np.full((480, 640, 3), 90, np.uint8)
        scene = pipeline.measure_frame(Frame(image=blank), track=False)
        assert scene.objects == []

    def test_downscaling_preserves_metric_results(self, synthetic_config, billboard_scene) -> None:
        """Resizing must not change the physical answer: the intrinsics scale
        with the image, so the geometry is identical."""
        from measurecv.pipeline.pipeline import MeasurementPipeline

        large_image = np.kron(billboard_scene["image"], np.ones((3, 3, 1), np.uint8))

        synthetic_config.runtime.max_image_side = 4000
        full = MeasurementPipeline(synthetic_config).measure_frame(
            Frame(image=large_image), track=False
        )
        synthetic_config.runtime.max_image_side = 640
        reduced = MeasurementPipeline(synthetic_config).measure_frame(
            Frame(image=large_image), track=False
        )

        assert full.objects and reduced.objects
        assert reduced.objects[0].dimensions.length.value == pytest.approx(
            full.objects[0].dimensions.length.value, rel=0.06
        )

    def test_boxes_are_reported_at_original_resolution(
        self, synthetic_config, billboard_scene
    ) -> None:
        from measurecv.pipeline.pipeline import MeasurementPipeline

        large_image = np.kron(billboard_scene["image"], np.ones((2, 2, 1), np.uint8))
        synthetic_config.runtime.max_image_side = 640
        scene = MeasurementPipeline(synthetic_config).measure_frame(
            Frame(image=large_image), track=False
        )

        assert scene.image_size == (1280, 960)
        assert scene.objects[0].detection.bbox.x2 > 640

    def test_measure_image_accepts_an_array(self, pipeline, billboard_scene) -> None:
        scene = pipeline.measure_image(billboard_scene["image"])
        assert len(scene.objects) == 1

    def test_rejects_non_rgb_array(self, pipeline) -> None:
        with pytest.raises(ValueError, match=r"\(H, W, 3\)"):
            pipeline.measure_image(np.zeros((100, 100), np.uint8))

    def test_full_artifacts_are_consistent(self, pipeline, billboard_scene) -> None:
        artifacts = pipeline.measure_frame_full(Frame(image=billboard_scene["image"]), track=False)
        assert len(artifacts.masks) == len(artifacts.scene.objects)
        assert artifacts.depth_map.shape == artifacts.image.shape[:2]
        assert artifacts.intrinsics.width == artifacts.image.shape[1]

    def test_tracking_assigns_stable_ids(self, pipeline, billboard_scene) -> None:
        image = billboard_scene["image"]
        ids = []
        for index in range(6):
            scene = pipeline.measure_frame(Frame(image=image, index=index), track=True)
            if scene.objects:
                ids.append(scene.objects[0].track_id)

        assert ids, "no tracked objects produced"
        assert len(set(ids)) == 1

    def test_stats_accumulate(self, pipeline, billboard_scene) -> None:
        for _ in range(3):
            pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=False)
        stats = pipeline.stats()
        assert stats["frames_processed"] == 3
        assert stats["latency_ms"]["count"] == 3

    def test_reset_clears_tracking_state(self, pipeline, billboard_scene) -> None:
        pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=True)
        pipeline.reset_state()
        assert pipeline.stats()["active_tracks"] == 0

    def test_scale_correction_changes_results(self, pipeline, billboard_scene) -> None:
        from measurecv.calibration.scale import ScaleCorrection

        baseline = pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=False)
        pipeline.set_scale_correction(ScaleCorrection(0.5, 0.01, 3))
        halved = pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=False)

        assert halved.objects[0].dimensions.length.value == pytest.approx(
            baseline.objects[0].dimensions.length.value * 0.5, rel=1e-6
        )


class TestSources:
    def test_open_image_file(self, tmp_path, billboard_scene) -> None:
        import cv2

        path = tmp_path / "scene.png"
        cv2.imwrite(str(path), cv2.cvtColor(billboard_scene["image"], cv2.COLOR_RGB2BGR))

        source = open_source(path)
        assert isinstance(source, ImageSource)
        frames = list(source)
        assert len(frames) == 1
        assert frames[0].image.shape == billboard_scene["image"].shape

    def test_open_directory_of_images(self, tmp_path, billboard_scene) -> None:
        import cv2

        for i in range(3):
            cv2.imwrite(
                str(tmp_path / f"f{i}.png"),
                cv2.cvtColor(billboard_scene["image"], cv2.COLOR_RGB2BGR),
            )
        assert len(list(open_source(tmp_path))) == 3

    def test_unsupported_extension_explains_options(self, tmp_path) -> None:
        from measurecv.core.exceptions import UnsupportedInputError

        path = tmp_path / "notes.txt"
        path.write_text("hello")
        with pytest.raises(UnsupportedInputError, match="Supported"):
            open_source(path)

    def test_missing_file_raises(self, tmp_path) -> None:
        from measurecv.core.exceptions import SourceError

        with pytest.raises(SourceError):
            ImageSource(tmp_path / "absent.png")

    def test_decode_bytes_round_trip(self, encoded_image, billboard_scene) -> None:
        decoded = decode_image_bytes(encoded_image)
        np.testing.assert_array_equal(decoded, billboard_scene["image"])

    def test_decode_garbage_raises(self) -> None:
        from measurecv.core.exceptions import UnsupportedInputError

        with pytest.raises(UnsupportedInputError, match="decode"):
            decode_image_bytes(b"not an image")

    def test_read_image_handles_unicode_path(self, tmp_path, billboard_scene) -> None:
        """np.fromfile + imdecode, because cv2.imread fails on non-ASCII paths
        on Windows."""
        import cv2

        path = tmp_path / "scène_测试.png"
        cv2.imwrite(
            str(tmp_path / "tmp.png"), cv2.cvtColor(billboard_scene["image"], cv2.COLOR_RGB2BGR)
        )
        (tmp_path / "tmp.png").rename(path)

        assert read_image(path).shape == billboard_scene["image"].shape


class TestExport:
    @pytest.fixture
    def scene(self, pipeline, billboard_scene):
        return pipeline.measure_frame(Frame(image=billboard_scene["image"]), track=False)

    def test_json_has_units_envelope(self, scene) -> None:
        payload = json.loads(scene_to_json(scene))
        assert payload["units"]["length"] == "m"
        assert payload["schema_version"] == "1.0"
        assert len(payload["scene"]["objects"]) == 1

    def test_json_is_serialisable_with_numpy_values(self, scene, tmp_path) -> None:
        path = write_json(tmp_path / "out.json", scene)
        reloaded = json.loads(path.read_text())
        assert reloaded["scene"]["objects"][0]["dimensions"]["length"]["value"] > 0

    def test_csv_columns_and_rows(self, scene, tmp_path) -> None:
        text = scene_to_csv([scene])
        lines = text.strip().splitlines()
        assert lines[0].startswith("frame_index,timestamp,track_id,label")
        assert len(lines) == 1 + len(scene.objects)

        path = write_csv(tmp_path / "out.csv", [scene])
        assert path.read_text(encoding="utf-8").count("\n") >= 2

    def test_ndjson_one_line_per_frame(self, scene, tmp_path) -> None:
        path = tmp_path / "out.ndjson"
        with NdjsonWriter(path) as writer:
            for _ in range(5):
                writer.write(scene)
            assert writer.count == 5

        lines = path.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 5
        assert all(json.loads(line)["objects"] for line in lines)

    def test_rle_round_trip(self) -> None:
        rng = np.random.default_rng(0)
        mask = rng.random((60, 80)) > 0.7
        np.testing.assert_array_equal(decode_rle(encode_rle(mask)), mask)

    def test_rle_handles_foreground_start(self) -> None:
        """COCO counts must begin with a zero run; a mask starting with
        foreground needs a leading empty run."""
        mask = np.ones((4, 4), bool)
        rle = encode_rle(mask)
        assert rle["counts"][0] == 0
        np.testing.assert_array_equal(decode_rle(rle), mask)

    def test_rle_empty_mask(self) -> None:
        mask = np.zeros((10, 10), bool)
        np.testing.assert_array_equal(decode_rle(encode_rle(mask)), mask)

    def test_coco_structure(self, scene) -> None:
        masks = [np.zeros(scene.image_size[::-1], bool) for _ in scene.objects]
        for mask in masks:
            mask[10:20, 10:20] = True

        coco = scene_to_coco([scene], [masks])

        assert set(coco) >= {"info", "images", "annotations", "categories"}
        assert len(coco["annotations"]) == len(scene.objects)
        # Measurements live under a namespaced key so the file stays valid COCO.
        assert "measurecv" in coco["annotations"][0]
        assert "segmentation" in coco["annotations"][0]

    def test_summarise(self, scene) -> None:
        result = summarise([scene, scene])
        assert result["frames"] == 2
        assert result["objects"] == 2 * len(scene.objects)


class TestVisualisation:
    @pytest.fixture
    def artifacts(self, pipeline, billboard_scene):
        return pipeline.measure_frame_full(Frame(image=billboard_scene["image"]), track=False)

    def test_draw_scene_returns_new_image(self, artifacts) -> None:
        original = artifacts.image.copy()
        annotated = draw_scene(artifacts.image, artifacts.scene)

        assert annotated.shape == artifacts.image.shape
        np.testing.assert_array_equal(artifacts.image, original)
        assert not np.array_equal(annotated, original)

    def test_draw_scene_with_masks_and_3d_boxes(self, artifacts) -> None:
        annotated = draw_scene(
            artifacts.image,
            artifacts.scene,
            masks=[m.mask for m in artifacts.masks],
            intrinsics=artifacts.intrinsics,
            style=AnnotationStyle(show_volume=True, show_3d_box=True),
        )
        assert annotated.dtype == np.uint8

    def test_handles_empty_scene(self, pipeline) -> None:
        blank = np.full((240, 320, 3), 90, np.uint8)
        scene = pipeline.measure_frame(Frame(image=blank), track=False)
        assert draw_scene(blank, scene).shape == blank.shape

    def test_depth_colourisation(self, artifacts) -> None:
        coloured = draw_depth_map(artifacts.depth_map.depth)
        assert coloured.shape == (*artifacts.depth_map.shape, 3)
        assert coloured.dtype == np.uint8

    def test_depth_colourisation_all_invalid(self) -> None:
        assert draw_depth_map(np.zeros((10, 10), np.float32)).sum() == 0

    def test_track_colors_are_distinct(self) -> None:
        colors = [track_color(i) for i in range(8)]
        assert len(set(colors)) == 8

    def test_labels_are_ascii_only(self, artifacts) -> None:
        """Regression: OpenCV's Hershey fonts have no glyphs outside ASCII.

        A '±' in a label is drawn byte-by-byte from its UTF-8 encoding and
        appears on the image as 'Â±'. Nothing raises -- the frame just renders
        wrong -- so the check has to be on the strings themselves.
        """
        from measurecv.viz.annotate import AnnotationStyle, _object_lines

        style = AnnotationStyle(show_volume=True, show_uncertainty=True)
        assert artifacts.scene.objects, "fixture produced nothing to check"
        for obj in artifacts.scene.objects:
            for line in _object_lines(obj, style):
                assert line.isascii(), f"non-ASCII in annotation label: {line!r}"

    def test_uncertainty_label_uses_the_principal_dimension(self, artifacts) -> None:
        """Regression: quoting the *worst* relative error let a near-zero
        thickness dominate and render '+/-35618.3%' over the frame."""
        from measurecv.viz.annotate import AnnotationStyle, _object_lines

        style = AnnotationStyle(show_uncertainty=True)
        for obj in artifacts.scene.objects:
            for line in _object_lines(obj, style):
                if line.startswith("+/-") and line.endswith("%"):
                    assert float(line[3:-1]) < 100.0, f"implausible uncertainty: {line}"

    def test_ply_round_trip(self, artifacts, tmp_path) -> None:
        from measurecv.geometry.backproject import backproject_depth_map

        cloud = backproject_depth_map(
            artifacts.depth_map, artifacts.intrinsics, stride=8, image=artifacts.image
        )
        path = write_ply(tmp_path / "cloud.ply", cloud)

        header = read_ply_header(path)
        assert header["format"] == "binary_little_endian"
        assert header["count"] == len(cloud)
        assert "red" in header["properties"]

    def test_ply_ascii(self, tmp_path) -> None:
        from measurecv.core.types import PointCloud

        cloud = PointCloud(np.arange(30, dtype=np.float64).reshape(10, 3))
        path = write_ply(tmp_path / "c.ply", cloud, binary=False)
        assert "ascii" in path.read_text()

    def test_obb_obj_export(self, artifacts, tmp_path) -> None:
        boxes = [o.dimensions for o in artifacts.scene.objects if o.dimensions]
        path = write_obb_obj(tmp_path / "boxes.obj", boxes, labels=["billboard"])
        text = path.read_text()
        assert "g billboard" in text
        assert text.count("\nv ") == 8 * len(boxes)


class TestApi:
    def test_health(self, api_client) -> None:
        response = api_client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] in ("ok", "starting")
        assert "device" in body

    def test_ready(self, api_client) -> None:
        assert api_client.get("/ready").status_code in (200, 503)

    def test_root_lists_endpoints(self, api_client) -> None:
        body = api_client.get("/").json()
        assert body["measure"] == "/v1/measure"

    def test_openapi_schema_is_valid(self, api_client) -> None:
        schema = api_client.get("/openapi.json").json()
        assert "/v1/measure" in schema["paths"]
        assert "/v1/calibration/intrinsics" in schema["paths"]

    def test_request_id_header(self, api_client) -> None:
        response = api_client.get("/health")
        assert response.headers.get("X-Request-ID")
        assert "Server-Timing" in response.headers

    def test_request_id_is_echoed(self, api_client) -> None:
        response = api_client.get("/health", headers={"X-Request-ID": "trace-abc"})
        assert response.headers["X-Request-ID"] == "trace-abc"

    def test_measure_endpoint(self, api_client, encoded_image, billboard_scene) -> None:
        response = api_client.post(
            "/v1/measure", files={"file": ("scene.png", encoded_image, "image/png")}
        )
        assert response.status_code == 200, response.text

        body = response.json()
        assert len(body["objects"]) == 1
        dims = body["objects"][0]["dimensions"]
        assert dims["length"]["value"] == pytest.approx(billboard_scene["true_width_m"], rel=0.06)
        assert dims["length"]["sigma"] > 0
        assert body["calibration_source"] == "assumed_fov"

    def test_measure_with_masks_and_images(self, api_client, encoded_image) -> None:
        response = api_client.post(
            "/v1/measure",
            files={"file": ("scene.png", encoded_image, "image/png")},
            data={
                "options": json.dumps(
                    {"include_masks": True, "include_annotated_image": True, "include_depth": True}
                )
            },
        )
        assert response.status_code == 200
        body = response.json()
        assert body["masks"] and "counts" in body["masks"][0]
        assert body["annotated_image_png_b64"]
        assert body["depth_png_b64"]

    def test_measure_with_explicit_intrinsics(self, api_client, encoded_image) -> None:
        response = api_client.post(
            "/v1/measure",
            files={"file": ("scene.png", encoded_image, "image/png")},
            data={
                "options": json.dumps(
                    {
                        "intrinsics": {
                            "fx": 800.0,
                            "fy": 800.0,
                            "cx": 319.5,
                            "cy": 239.5,
                            "width": 640,
                            "height": 480,
                            "focal_uncertainty": 0.01,
                        }
                    }
                )
            },
        )
        assert response.status_code == 200
        assert response.json()["calibration_source"] == "provided"

    def test_intrinsics_size_mismatch_is_rejected(self, api_client, encoded_image) -> None:
        """Intrinsics are resolution-dependent; a mismatch must not be silently
        accepted."""
        response = api_client.post(
            "/v1/measure",
            files={"file": ("scene.png", encoded_image, "image/png")},
            data={
                "options": json.dumps(
                    {
                        "intrinsics": {
                            "fx": 800.0,
                            "fy": 800.0,
                            "cx": 100,
                            "cy": 100,
                            "width": 1920,
                            "height": 1080,
                        }
                    }
                )
            },
        )
        assert response.status_code == 422
        assert "resolution-dependent" in response.text

    def test_bad_options_json(self, api_client, encoded_image) -> None:
        response = api_client.post(
            "/v1/measure",
            files={"file": ("scene.png", encoded_image, "image/png")},
            data={"options": "{not json"},
        )
        assert response.status_code == 400

    def test_corrupt_upload_returns_415(self, api_client) -> None:
        response = api_client.post(
            "/v1/measure", files={"file": ("bad.png", b"garbage", "image/png")}
        )
        assert response.status_code == 415
        assert response.json()["code"] == "unsupported_input"

    def test_batch_endpoint(self, api_client, encoded_image) -> None:
        response = api_client.post(
            "/v1/measure/batch",
            files=[
                ("files", ("a.png", encoded_image, "image/png")),
                ("files", ("b.png", encoded_image, "image/png")),
            ],
        )
        assert response.status_code == 200
        body = response.json()
        assert body["count"] == 2
        assert body["succeeded"] == 2

    def test_batch_isolates_failures(self, api_client, encoded_image) -> None:
        """One corrupt upload must not discard the work done on the others."""
        response = api_client.post(
            "/v1/measure/batch",
            files=[
                ("files", ("good.png", encoded_image, "image/png")),
                ("files", ("bad.png", b"garbage", "image/png")),
            ],
        )
        body = response.json()
        assert body["succeeded"] == 1
        assert body["failed"] == 1
        assert "error" in body["results"][1]

    def test_models_endpoint(self, api_client) -> None:
        body = api_client.get("/v1/models").json()
        assert body["backends"]["detection"] == "synthetic"

    def test_config_endpoint_hides_secrets(self, api_client) -> None:
        body = api_client.get("/v1/config").json()
        assert "api_keys" not in body["api"]

    def test_calibration_profile_when_absent(self, api_client) -> None:
        body = api_client.get("/v1/calibration/profile").json()
        assert body["profile"] is None
        assert "assumed" in body["message"]

    def test_reference_catalogue(self, api_client) -> None:
        body = api_client.get("/v1/calibration/references").json()
        assert body["references_m"]["credit_card_long"] == pytest.approx(0.0856)

    def test_scale_correction_round_trip(self, api_client) -> None:
        response = api_client.post(
            "/v1/calibration/scale",
            json={"measured_m": [0.090], "truth_m": [0.0856], "reference": "credit_card_long"},
        )
        assert response.status_code == 200
        assert response.json()["correction"]["factor"] == pytest.approx(0.0856 / 0.090, rel=1e-3)

        assert api_client.delete("/v1/calibration/scale").status_code == 200

    def test_scale_rejects_mismatched_lengths(self, api_client) -> None:
        response = api_client.post(
            "/v1/calibration/scale", json={"measured_m": [1.0, 2.0], "truth_m": [1.0]}
        )
        assert response.status_code == 422

    def test_calibration_needs_enough_views(self, api_client, encoded_image) -> None:
        response = api_client.post(
            "/v1/calibration/intrinsics",
            files=[("files", ("a.png", encoded_image, "image/png"))],
        )
        assert response.status_code == 422

    def test_metrics_endpoint(self, api_client) -> None:
        response = api_client.get("/metrics")
        assert response.status_code == 200

    def test_unknown_route_404(self, api_client) -> None:
        assert api_client.get("/v1/nope").status_code == 404


class TestLiveStreaming:
    """The browser live-view path: page, WebSocket protocol, session threading."""

    def test_live_page_serves(self, api_client) -> None:
        response = api_client.get("/v1/stream/live")
        assert response.status_code == 200
        body = response.text
        # The pieces the page cannot work without.
        for token in ("getUserMedia", "/v1/stream/ws", "requestAnimationFrame", "toBlob"):
            assert token in body, f"live page missing {token}"

    def test_live_page_warns_about_secure_context(self, api_client) -> None:
        """getUserMedia is blocked off localhost without HTTPS; a phone on the
        LAN hits this, and a silent null camera is a terrible failure mode."""
        assert "isSecureContext" in api_client.get("/v1/stream/live").text

    def test_websocket_measures_a_pushed_frame(self, api_client, encoded_image) -> None:
        """Exactly what the browser does: push JPEG bytes, get JSON back."""
        with api_client.websocket_connect("/v1/stream/ws") as ws:
            ws.send_bytes(encoded_image)
            message = ws.receive_json()

        assert message["type"] == "measurement"
        assert len(message["objects"]) == 1
        assert message["objects"][0]["dimensions"]["length"]["value"] > 0

    def test_websocket_assigns_track_ids(self, api_client, encoded_image) -> None:
        """Streaming enables tracking, which is what temporal fusion keys on."""
        with api_client.websocket_connect("/v1/stream/ws") as ws:
            ids = []
            for _ in range(3):
                ws.send_bytes(encoded_image)
                message = ws.receive_json()
                if message["objects"]:
                    ids.append(message["objects"][0]["detection"]["track_id"])

        assert ids and all(i is not None for i in ids)
        assert len(set(ids)) == 1, f"identity switched across frames: {ids}"

    def test_websocket_reports_bad_frames_without_dying(self, api_client, encoded_image) -> None:
        with api_client.websocket_connect("/v1/stream/ws") as ws:
            ws.send_bytes(b"not an image")
            error = ws.receive_json()
            assert error["type"] == "error"

            # The connection must survive a bad frame.
            ws.send_bytes(encoded_image)
            assert ws.receive_json()["type"] == "measurement"

    def test_websocket_control_commands(self, api_client, encoded_image) -> None:
        with api_client.websocket_connect("/v1/stream/ws") as ws:
            ws.send_bytes(encoded_image)
            ws.receive_json()

            ws.send_text(json.dumps({"command": "stats"}))
            stats = ws.receive_json()
            assert stats["type"] == "stats"
            assert stats["processed"] >= 1

            ws.send_text(json.dumps({"command": "reset"}))
            assert ws.receive_json()["command"] == "reset"

            ws.send_text(json.dumps({"command": "bogus"}))
            assert ws.receive_json()["type"] == "error"


class TestLiveSession:
    """The threaded session that decouples display rate from measurement rate."""

    def _source(self, image, frames: int):
        from measurecv.core.types import Frame
        from measurecv.pipeline.sources import FrameSource

        class _Fixed(FrameSource):
            def __iter__(self):
                for i in range(frames):
                    yield Frame(image=image, index=i, timestamp=float(i))

        return _Fixed()

    def test_display_outpaces_measurement(self, pipeline, billboard_scene) -> None:
        """The whole point: frames flow through regardless of measurement cost.

        Frames are consumed as fast as the source yields them while the worker
        measures at its own pace, so nearly all frames are skipped by the
        worker and none are blocked from the consumer.
        """
        from measurecv.pipeline.live import LiveSession

        session = LiveSession(pipeline, self._source(billboard_scene["image"], 200), track=True)
        with session:
            seen = list(session.stream())
            # The consumer never waits for the worker, so a measurement may
            # still be in flight when the source runs dry. Wait explicitly.
            result = session.wait_for_result(timeout=30.0)

        assert len(seen) == 200, "consumer was throttled by the measurement worker"
        assert session.stats.frames_displayed == 200
        assert session.stats.frames_skipped > 0, "worker should not see every frame"
        assert session.stats.errors == 0
        assert result is not None or session.stats.frames_measured >= 1

    def test_results_carry_age(self, pipeline, billboard_scene) -> None:
        import time

        from measurecv.pipeline.live import LiveSession

        session = LiveSession(pipeline, self._source(billboard_scene["image"], 60), track=True)
        with session:
            result = None
            for _frame, res in session.stream():
                if res is not None:
                    result = res
                    break
                time.sleep(0.01)

        assert result is not None, "no measurement completed"
        assert result.age_s >= 0.0
        assert result.latency_ms > 0.0
        assert len(result.masks) == len(result.scene.objects)

    def test_compose_renders_without_a_result(self, pipeline, billboard_scene) -> None:
        """Before the first measurement lands there is still a frame to show."""
        from measurecv.core.types import Frame
        from measurecv.pipeline.live import LiveStats, compose_live_frame

        frame = Frame(image=billboard_scene["image"])
        canvas = compose_live_frame(frame, None, LiveStats())

        assert canvas.shape == billboard_scene["image"].shape
        assert not np.array_equal(canvas, billboard_scene["image"])

    def test_stop_is_idempotent(self, pipeline, billboard_scene) -> None:
        from measurecv.pipeline.live import LiveSession

        session = LiveSession(pipeline, self._source(billboard_scene["image"], 2), track=False)
        session.start()
        session.stop()
        session.stop()


class TestDepthReuse:
    """runtime.depth_every_n_frames -- the main live-mode saving."""

    def test_depth_is_reused_and_flagged(self, synthetic_config, billboard_scene) -> None:
        from measurecv.core.types import Frame
        from measurecv.pipeline.pipeline import MeasurementPipeline

        synthetic_config.runtime.depth_every_n_frames = 3
        pipeline = MeasurementPipeline(synthetic_config)

        warnings = []
        for i in range(4):
            scene = pipeline.measure_frame(
                Frame(image=billboard_scene["image"], index=i), track=False
            )
            warnings.append(any("depth reused" in w for w in scene.warnings))

        # Fresh, reused, reused, fresh again.
        assert warnings == [False, True, True, False]

    def test_reuse_does_not_change_the_answer_on_a_static_scene(
        self, synthetic_config, billboard_scene
    ) -> None:
        from measurecv.core.types import Frame
        from measurecv.pipeline.pipeline import MeasurementPipeline

        image = billboard_scene["image"]
        baseline = MeasurementPipeline(synthetic_config).measure_frame(Frame(image=image))

        synthetic_config.runtime.depth_every_n_frames = 5
        cached = MeasurementPipeline(synthetic_config)
        cached.measure_frame(Frame(image=image, index=0))
        reused = cached.measure_frame(Frame(image=image, index=1))

        assert reused.objects[0].dimensions.length.value == pytest.approx(
            baseline.objects[0].dimensions.length.value, rel=1e-9
        )

    def test_reset_clears_the_depth_cache(self, synthetic_config, billboard_scene) -> None:
        from measurecv.core.types import Frame
        from measurecv.pipeline.pipeline import MeasurementPipeline

        synthetic_config.runtime.depth_every_n_frames = 5
        pipeline = MeasurementPipeline(synthetic_config)
        pipeline.measure_frame(Frame(image=billboard_scene["image"], index=0))
        pipeline.reset_state()

        scene = pipeline.measure_frame(Frame(image=billboard_scene["image"], index=1))
        assert not any("depth reused" in w for w in scene.warnings)


class TestApiAuth:
    @pytest.fixture
    def secured_client(self, synthetic_config):
        from fastapi.testclient import TestClient

        from measurecv.api.app import create_app

        synthetic_config.api.api_keys = ["secret-key"]
        with TestClient(create_app(synthetic_config)) as client:
            yield client

    def test_health_stays_open(self, secured_client) -> None:
        """Health checks must not require credentials or orchestrators break."""
        assert secured_client.get("/health").status_code == 200

    def test_missing_key_rejected(self, secured_client, encoded_image) -> None:
        response = secured_client.post(
            "/v1/measure", files={"file": ("a.png", encoded_image, "image/png")}
        )
        assert response.status_code == 401

    def test_wrong_key_rejected(self, secured_client, encoded_image) -> None:
        response = secured_client.post(
            "/v1/measure",
            files={"file": ("a.png", encoded_image, "image/png")},
            headers={"X-API-Key": "wrong"},
        )
        assert response.status_code == 403

    def test_correct_key_accepted(self, secured_client, encoded_image) -> None:
        response = secured_client.post(
            "/v1/measure",
            files={"file": ("a.png", encoded_image, "image/png")},
            headers={"X-API-Key": "secret-key"},
        )
        assert response.status_code == 200
