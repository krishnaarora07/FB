import urllib.request
import os
from moviepy.editor import VideoFileClip, CompositeVideoClip

def main():
    urllib.request.urlretrieve("https://test-videos.co.uk/vids/bigbuckbunny/mp4/h264/720/Big_Buck_Bunny_720_10s_1MB.mp4", "sample.mp4")

    raw_fg = VideoFileClip("sample.mp4").without_audio().subclip(0, 1)
    raw_bg = VideoFileClip("sample.mp4").without_audio().subclip(0, 1)

    length = 1

    fg_clip = raw_fg.resize(width=1080)
    if fg_clip.h > 960:
        fg_clip = fg_clip.resize(height=960)

    bg_clip = raw_bg.resize(height=960)
    if bg_clip.w < 1080:
        bg_clip = bg_clip.resize(width=1080)

    x_center = bg_clip.w / 2
    y_center = bg_clip.h / 2
    bg_clip = bg_clip.crop(x1=x_center - 540, y1=y_center - 480, x2=x_center + 540, y2=y_center + 480)

    def blur_frame(image):
        from PIL import Image, ImageFilter
        import numpy as np
        img = Image.fromarray(image).convert("RGB")
        img.thumbnail((270, 240))
        img = img.filter(ImageFilter.GaussianBlur(radius=5))
        img = img.resize((1080, 960), Image.Resampling.BILINEAR)
        return np.array(img)

    bg_clip = bg_clip.fl_image(blur_frame)

    clip = CompositeVideoClip([bg_clip, fg_clip.set_position("center")], size=(1080, 960)).set_duration(length)
    clip.write_videofile("test_output.mp4", fps=24, codec="libx264")
    print("Done generating test_output.mp4")

if __name__ == "__main__":
    main()
