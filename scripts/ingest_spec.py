import os
import requests

def download_and_ingest_pdf():
    # OSHA Fall Protection guidelines
    url = "https://www.osha.gov/sites/default/files/publications/OSHA3146.pdf"
    pdf_path = os.path.join(os.path.dirname(__file__), "..", "data", "OSHA_Fall_Protection.pdf")
    
    os.makedirs(os.path.dirname(pdf_path), exist_ok=True)
    
    if not os.path.exists(pdf_path):
        print(f"Downloading OSHA Fall Protection PDF from {url}...")
        response = requests.get(url, stream=True)
        if response.status_code == 200:
            with open(pdf_path, 'wb') as f:
                for chunk in response.iter_content(1024):
                    f.write(chunk)
            print(f"Downloaded to {pdf_path}")
        else:
            print(f"Failed to download PDF. Status: {response.status_code}")
            return
    else:
        print(f"PDF already exists at {pdf_path}")
        
    print("Sending PDF to backend for parsing and indexing...")
    api_url = "http://localhost:8000/api/v1/drawing/parse"
    
    with open(pdf_path, 'rb') as f:
        files = {'file': ('OSHA_Fall_Protection.pdf', f, 'application/pdf')}
        data = {'is_tabular': False}
        res = requests.post(api_url, files=files, data=data)
        
    if res.status_code == 200:
        print("Success!")
        print(res.json())
    else:
        print(f"Error: {res.status_code} - {res.text}")

if __name__ == "__main__":
    download_and_ingest_pdf()
