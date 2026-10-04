import os
from tempfile import mkdtemp
from shutil import rmtree

cv2_successful = False
try:
    import cv2
    import ffmpeg
    cv2_successful = True
except:
    print("failed to include cv2!")
    cv2_successful = False

from src.exceptions.posterboard_exceptions import VideoLengthException
from src.controllers.files_handler import get_bundle_files

from PySide6.QtCore import QCoreApplication

ignore_pb_frame_limit = False

def set_ignore_frame_limit(value: bool):
    global ignore_pb_frame_limit
    ignore_pb_frame_limit = value

def convert_to_mov(input_file: str, output_file: str = None):
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
    cam = cv2.VideoCapture(video_path)
    assets_path = os.path.join(output_file, "assets")
    frame_count = int(cam.get(cv2.CAP_PROP_FRAME_COUNT))
    FRAME_LIMIT = 400
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
    currentframe = 0
    width = int(cam.get(cv2.CAP_PROP_FRAME_WIDTH))
    height = int(cam.get(cv2.CAP_PROP_FRAME_HEIGHT))
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
        fps = cam.get(cv2.CAP_PROP_FPS)
        duration = frame_count / fps
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
        while(True):
            # reading from frame 
            ret,frame = cam.read() 
        
            if ret: 
                # if video is still left continue creating images 
                name = 'assets/' + str(currentframe) + '.jpg'
                if update_label:
                    update_label(QCoreApplication.tr('Creating {0}...').format(name))
                print('Creating...' + name)
        
                # writing the extracted images
                cv2.imwrite(os.path.join(output_file.removeprefix(u"\\\\?\\"), name), frame)
                caml.write(f"\t\t\t<CGImage src=\"{name}\"/>\n")
        
                # increasing counter so that it will
                # show how many frames are created
                currentframe += 1
            else:
                break
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