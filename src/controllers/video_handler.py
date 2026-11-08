import os
from shutil import rmtree
from tempfile import mkdtemp

# OpenCV (which drags in numpy) and ffmpeg together cost ~160 ms to import and
# are only needed when a video wallpaper is actually converted. This module is
# imported at startup through the tweak registry, so the imports are deferred to
# the first video operation via _ensure_video_libs().
cv2 = None
ffmpeg = None
# None = not resolved yet, True/False mirror the historical module flag once
# _ensure_video_libs() has run.
cv2_successful = None


def _ensure_video_libs() -> bool:
    """Import cv2/ffmpeg on first use. Returns True when both are available."""
    global cv2, ffmpeg, cv2_successful
    if cv2_successful is None:
        try:
            import cv2 as _cv2
            import ffmpeg as _ffmpeg
            cv2, ffmpeg = _cv2, _ffmpeg
            cv2_successful = True
        except Exception:
            print("failed to include cv2!")
            cv2_successful = False
    return cv2_successful


from src.controllers.files_handler import get_bundle_files
from src.exceptions.posterboard_exceptions import VideoLengthException
from src.utils.i18n import QCoreApplication

ignore_pb_frame_limit = False

def set_ignore_frame_limit(value: bool):
    global ignore_pb_frame_limit
    ignore_pb_frame_limit = value

# Guards for the frame-sequence export (issue #86). A CAKeyframeAnimation on
# "contents" keeps EVERY key image decoded in memory on the device, so the
# wallpaper renderer's footprint is
#   frames x frame_width x frame_height x 4 bytes (RGBA)
# no matter how small the JPEGs are on disk — a 300-frame 1080x1920 export
# decodes to ~2.5 GB. Over the budget the wallpaper extension is jetsammed:
# it falls back to a still frame, blinks black for ~1 s when the extension
# respawns (repeatedly for about a minute after a cold boot), and settles
# only once the animation has been evicted or cached. The exporter therefore
# keeps every export inside the decoded-pixel budget: it caps the frame rate,
# and skips/downscales frames as needed. Duration is always preserved; a
# "linear" calculation mode cross-fades between the remaining frames.
# The "Ignore Posterboard Frame Limit" switch skips all of this and exports
# the source verbatim (user override).
FRAME_LIMIT = 400          # hard source-frame count cap (legacy switch behaviour)
MAX_SOURCE_FPS = 30
MIN_OUTPUT_FPS = 10
MAX_SEQUENCE_DECODED_BYTES = 512 * 1024 * 1024
JPEG_QUALITY = 85
# All supported iPhone screen classes are @3x: rendering a frame larger than
# the document at device scale times the depth scale wastes memory on pixels
# that can never reach the screen. 390x844 * 3 * 1.3 -> 1521x3292 max.
DEVICE_SCALE = 3

def convert_to_mov(input_file: str, output_file: str = None):
    _ensure_video_libs()
    # if there is no output file specified, create a temp file then return contents
    if output_file == None:
        tmpdir = mkdtemp()
        tmp = os.path.join(tmpdir, "vid.mov")
        convert_to_mov(input_file, tmp)
        with open(tmp, "rb") as tmpfile:
            contents = tmpfile.read()
        rmtree(tmpdir)
        return contents
    inp = ffmpeg.input(input_file)
    out = ffmpeg.output(inp, output_file, f='mov', vcodec='copy', acodec='copy')
    ffmpeg_bin = get_bundle_files("ffmpeg/bin")
    if os.name == 'nt' and os.path.exists(ffmpeg_bin):
        os.environ['PATH'] += os.pathsep + ffmpeg_bin
    ffmpeg.run(out)

def create_caml(video_path: str, output_file: str, auto_reverses: bool, calculationMode: str, update_label=lambda x: None,
                bounds_scale: float = 1.0, offset_x: float = 0, offset_y: float = 0,
                doc_width: int = 390, doc_height: int = 844, layer_name: str = "Background"):
    """Write the CAML that animates ``video_path`` as a frame sequence.

    ``bounds_scale``/``offset_*`` place the animated layer inside the document.
    The PosterKit depth effect is not a 3D transform: it parallaxes planes whose
    bounds and origin differ from the 390x844 document, exactly like The Odyssey's
    ``spartanbg`` layer (bounds 1852x4104 at y=545.9 in a 390x844 document). A
    layer rendered at scale 1.0 dead-centre has nothing to parallax against and
    reads as a flat wallpaper, so callers that want depth pass a scale > 1 and an
    offset.
    """
    _ensure_video_libs()
    cam = cv2.VideoCapture(video_path)
    assets_path = os.path.join(output_file, "assets")
    frame_count = int(cam.get(cv2.CAP_PROP_FRAME_COUNT))
    reverse = 0
    if auto_reverses:
        reverse = 1
    if not ignore_pb_frame_limit and frame_count > FRAME_LIMIT:
        raise VideoLengthException(FRAME_LIMIT)
    try:
        # creating a folder named data
        if not os.path.exists(assets_path): 
            os.makedirs(assets_path, exist_ok=True) 
    # if not created then raise error
    except OSError:
        print ('Error: Creating directory of data')
    
    # frame
    source_width = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
    source_height = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cam.get(cv2.CAP_PROP_FPS)
    # The whole loop keeps its playback duration: sampling every Nth frame
    # keeps N times the per-frame display time (linear calculation mode then
    # cross-fades between the sampled frames).
    duration = frame_count / fps if fps > 0 else 0
    
    # Memory-fit adaptation (issue #86): decide downscale + frame stride so
    # the full decoded sequence stays inside MAX_SEQUENCE_DECODED_BYTES.
    downscale = 1.0
    stride = 1
    if not ignore_pb_frame_limit:
        max_w = doc_width * DEVICE_SCALE * bounds_scale
        max_h = doc_height * DEVICE_SCALE * bounds_scale
        if source_width > max_w or source_height > max_h:
            # Render-relevant ceiling: the picture is scaled down to cover the
            # document on the device, so pixels beyond this width/height are
            # never shown and would only burn render memory.
            downscale = min(max_w / source_width, max_h / source_height)
        if fps > MAX_SOURCE_FPS:
            stride = max(1, round(fps / MAX_SOURCE_FPS))
        frame_bytes = round(source_width * downscale) * round(source_height * downscale) * 4
        samples = (frame_count + stride - 1) // stride
        if frame_bytes * samples > MAX_SEQUENCE_DECODED_BYTES:
            stride = max(stride, -(-frame_count // max(1, MAX_SEQUENCE_DECODED_BYTES // frame_bytes)))
        if fps > 0:
            # Prefer fluid motion over native sharpness: below the output-fps
            # floor a stepping animation stutters, so trade pixels for frames
            # instead (fit the budget with the floor stride by downscaling).
            floor_stride = max(1, int(fps // MIN_OUTPUT_FPS))  # keeps fps/stride >= MIN_OUTPUT_FPS
            if fps / stride < MIN_OUTPUT_FPS:
                floor_samples = -(-frame_count // floor_stride)
                allowed_pixels = (MAX_SEQUENCE_DECODED_BYTES // floor_samples) // 4
                current_pixels = round(source_width * downscale) * round(source_height * downscale)
                if allowed_pixels < current_pixels:
                    downscale *= (allowed_pixels / current_pixels) ** 0.5
                stride = floor_stride
    if downscale < 1.0:
        width = max(1, round(source_width * downscale))
        height = max(1, round(source_height * downscale))
    else:
        width, height = source_width, source_height
    print(f"Export: {source_width}x{source_height} @ {fps:.1f} fps, {frame_count} frames -> "
          f"stride {stride}, scale {downscale:.2f} -> {width}x{height}, "
          f"{-(-frame_count // stride)} output frames")
    if stride > 1 or downscale < 1.0:
        update_label(QCoreApplication.tr(
            'Source: {0}x{1}, {2:.1f} fps, {3} frames - exporting {4} frames at {5:.1f} fps ({6}x{7}) '
            'to stay inside the device memory budget').format(
            source_width, source_height, fps, frame_count, -(-frame_count // stride),
            fps / stride if stride else 0, width, height))
    # Depth plane geometry: the package document must be the logical screen
    # (matching the background/foreground packages) or PosterKit 27 refuses the
    # floating view and collapses it into the foreground view. The animated
    # content itself stays oversized + off-centre so the depth pass has travel
    # to parallax (The Odyssey's spartanbg is 1852x4104 inside a 390x844 doc).
    cover = max(doc_width / width, doc_height / height)
    layer_scale = cover * bounds_scale
    center_x = doc_width / 2 + offset_x
    center_y = doc_height / 2 + offset_y

    with open(os.path.join(output_file, "main.caml"), "w") as caml:
        # write caml header
        caml.write(f"""<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <CALayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 {doc_width} {doc_height}" contentsFormat="RGBA8" geometryFlipped="1" hidden="0" name="Root Layer" position="{int(doc_width / 2)} {int(doc_height / 2)}">
    <backgroundColor opacity="0" value="1 0 1"/>
    <sublayers>
      <CALayer id="{layer_name}" allowsEdgeAntialiasing="1" allowsGroupOpacity="1" anchorPoint="0 0" bounds="0 0 {doc_width} {doc_height}" contentsFormat="RGBA8" geometryFlipped="0" hidden="0" name="{layer_name}" position="0 0">
	<sublayers>
	  <CATransformLayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" allowsHitTesting="1" bounds="0 0 {width} {height}" contentsFormat="RGBA8" cornerCurve="circular" name="Chip" position="{center_x} {center_y}" transform="scale({layer_scale}, {layer_scale}, 1)">
	    <sublayers>
	      <CALayer allowsEdgeAntialiasing="1" allowsGroupOpacity="1" bounds="0 0 {width} {height}" contentsFormat="RGBA8" cornerCurve="circular" name="CALayer1" position="{int(width / 2)} {int(height / 2)}">
		<contents type="CGImage" src="assets/0.jpg"/>
		<animations>
		  <animation type="CAKeyframeAnimation" calculationMode="{calculationMode}" keyPath="contents" beginTime="1e-100" duration="{duration}" removedOnCompletion="0" repeatCount="inf" repeatDuration="0" speed="1" timeOffset="0" autoreverses="{reverse}">
		    <values>\n""")
        source_index = 0
        while True:
            # reading from frame 
            ret,frame = cam.read() 
            if not ret:
                break
        
            if source_index % stride == 0:
                # if video is still left continue creating images 
                name = 'assets/' + str(source_index) + '.jpg'
                if update_label:
                    update_label(QCoreApplication.tr('Creating {0}...').format(name))
                print('Creating...' + name)
        
                # writing the extracted images
                if downscale < 1.0:
                    frame = cv2.resize(frame, (width, height), interpolation=cv2.INTER_AREA)
                cv2.imwrite(os.path.join(output_file.removeprefix(u"\\\\?\\"), name), frame,
                            [cv2.IMWRITE_JPEG_QUALITY, JPEG_QUALITY])
                caml.write(f"\t\t\t<CGImage src=\"{name}\"/>\n")
        
            # increasing counter so that it will
            # show how many frames are created
            source_index += 1
        caml.write("""		    </values>
		  </animation>
		</animations>
	      </CALayer>
	    </sublayers>
	  </CATransformLayer>
	</sublayers>
      </CALayer>
    </sublayers>
    <states>
      <LKState name="Locked">
	<elements/>
      </LKState>
      <LKState name="Unlock">
	<elements/>
      </LKState>
      <LKState name="Sleep">
	<elements/>
      </LKState>
    </states>
    <stateTransitions>
      <LKStateTransition fromState="*" toState="Unlock">
	<elements/>
      </LKStateTransition>
      <LKStateTransition fromState="Unlock" toState="*">
	<elements/>
      </LKStateTransition>
      <LKStateTransition fromState="*" toState="Locked">
	<elements/>
      </LKStateTransition>
      <LKStateTransition fromState="Locked" toState="*">
	<elements/>
      </LKStateTransition>
      <LKStateTransition fromState="*" toState="Sleep">
	<elements/>
      </LKStateTransition>
      <LKStateTransition fromState="Sleep" toState="*">
	<elements/>
      </LKStateTransition>
    </stateTransitions>
  </CALayer>
</caml>
""")
    
    # Release all space and windows once done
    cam.release()
    cv2.destroyAllWindows()

    # Write the other caml
    with open(os.path.join(output_file, "index.xml"), "w") as index:
        index.write(f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
	<key>assetManifest</key>
	<string>assetManifest.caml</string>
	<key>documentHeight</key>
	<real>{doc_height}</real>
	<key>documentResizesToView</key>
	<false/>
	<key>documentWidth</key>
	<real>{doc_width}</real>
	<key>dynamicGuidesEnabled</key>
	<true/>
	<key>geometryFlipped</key>
	<false/>
	<key>guidesEnabled</key>
	<true/>
	<key>interactiveMouseEventsEnabled</key>
	<true/>
	<key>interactiveShowsCursor</key>
	<true/>
	<key>interactiveTouchEventsEnabled</key>
	<false/>
	<key>loopEnd</key>
	<real>+infinity</real>
	<key>loopStart</key>
	<real>0.0</real>
	<key>loopingEnabled</key>
	<true/>
	<key>multitouchDisablesMouse</key>
	<false/>
	<key>multitouchEnabled</key>
	<false/>
	<key>presentationMouseEventsEnabled</key>
	<true/>
	<key>presentationShowsCursor</key>
	<true/>
	<key>presentationTouchEventsEnabled</key>
	<false/>
	<key>publishedObjectNames</key>
	<array>
		<string>{layer_name}</string>
	</array>
	<key>rootDocument</key>
	<string>main.caml</string>
	<key>savesWindowFrame</key>
	<false/>
	<key>scalesToFitInPlayer</key>
	<true/>
	<key>showsTouches</key>
	<true/>
	<key>snappingEnabled</key>
	<true/>
	<key>timelineMarkers</key>
	<string>[(null)]</string>
	<key>touchesColor</key>
	<string>1 1 0 0.8</string>
	<key>unitsInPixelsInPlayer</key>
	<false/>
</dict>
</plist>
""")

    # Mica asset manifest: required for the package to load. The template ships
    # it, but the legacy use_foreground branch renames the .ca away and recreates
    # it here, so write it explicitly to keep every generated package complete.
    with open(os.path.join(output_file, "assetManifest.caml"), "w") as manifest:
        manifest.write("""<?xml version="1.0" encoding="UTF-8"?>

<caml xmlns="http://www.apple.com/CoreAnimation/1.0">
  <MicaAssetManifest>
    <modules type="NSArray"/>
  </MicaAssetManifest>
</caml>
""")