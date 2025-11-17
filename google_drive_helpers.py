import os
import pickle
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from google.auth.transport.requests import Request

# If modifying these scopes, delete the file token.pickle.
SCOPES = [
    'https://www.googleapis.com/auth/drive.file',
    'https://www.googleapis.com/auth/spreadsheets'
]

def get_google_services():
    """
    Authenticate and return Google Drive and Sheets service objects.
    """
    creds = None
    if os.path.exists('token.pickle'):
        with open('token.pickle', 'rb') as token:
            creds = pickle.load(token)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                'credentials.json', SCOPES)
            creds = flow.run_local_server(port=0)
        with open('token.pickle', 'wb') as token:
            pickle.dump(creds, token)
    drive_service = build('drive', 'v3', credentials=creds)
    sheets_service = build('sheets', 'v4', credentials=creds)
    return drive_service, sheets_service

def create_drive_folder(drive_service, folder_name, parent_id=None):
    file_metadata = {
        'name': folder_name,
        'mimeType': 'application/vnd.google-apps.folder'
    }
    if parent_id:
        file_metadata['parents'] = [parent_id]
    folder = drive_service.files().create(body=file_metadata, fields='id').execute()
    return folder.get('id')

def create_google_sheet(drive_service, sheets_service, sheet_name, parent_folder_id=None):
    file_metadata = {
        'name': sheet_name,
        'mimeType': 'application/vnd.google-apps.spreadsheet'
    }
    if parent_folder_id:
        file_metadata['parents'] = [parent_folder_id]
    sheet = drive_service.files().create(body=file_metadata, fields='id').execute()
    return sheet.get('id')

def list_drive_folders(drive_service, parent_id='root'):
    """
    List all folders under a given parent folder in Google Drive.

    Args:
        drive_service: The authenticated Google Drive service object.
        parent_id (str): The ID of the parent folder (default is 'root').

    Returns:
        List[Dict]: A list of folder metadata dictionaries.
    """
    query = f"'{parent_id}' in parents and mimeType = 'application/vnd.google-apps.folder' and trashed = false"
    results = drive_service.files().list(q=query, fields="files(id, name)").execute()
    return results.get('files', [])

# Example usage:
# drive_service, sheets_service = get_google_services()
# folder_id = create_drive_folder(drive_service, 'My New Folder')
# sheet_id = create_google_sheet(drive_service, sheets_service, 'My New Sheet', folder_id)
# folders = list_drive_folders(drive_service, parent_id='root')
# for folder in folders:
#     print(folder['id'], folder['name'])
