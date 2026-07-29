import os
import urllib.request
import sys

def download_video():
    # A short, open-source sample video of a construction site or people walking
    # Using a generic test video url. For a real hackathon, a specific construction video is better.
    # We'll use a widely available test video (e.g. from OpenCV or similar).
    url = "https://github.com/intel-iot-devkit/sample-videos/raw/master/people-detection.mp4"
    data_dir = os.path.join(os.path.dirname(__file__), '..', 'data')
    os.makedirs(data_dir, exist_ok=True)
    
    file_path = os.path.join(data_dir, 'sample_construction.mp4')
    
    if os.path.exists(file_path):
        print(f"Video already exists at {file_path}")
        return
        
    print(f"Downloading sample video from {url}...")
    
    def report(block_num, block_size, total_size):
        downloaded = block_num * block_size
        percent = min(100, downloaded * 100 / total_size)
        sys.stdout.write(f"\rDownloaded {percent:.2f}%")
        sys.stdout.flush()

    try:
        urllib.request.urlretrieve(url, file_path, reporthook=report)
        print(f"\nSuccessfully downloaded video to {file_path}")
    except Exception as e:
        print(f"\nFailed to download video: {e}")

if __name__ == "__main__":
    download_video()
