from google import service_account
import googleapiclient.discovery
from urllib.parse import urlencode
from common import (
    google_service_account, 
    google_customer_key,
    google_auth_with
)

SCOPES = ['https://www.googleapis.com/auth/cloud-identity.groups']
SERVICE_ACCOUNT_FILE = google_service_account
CUSTOMER_ID = google_customer_key

def create_service():
    credentials = service_account.Credentials.from_service_account_file(
        SERVICE_ACCOUNT_FILE, scopes=SCOPES)
    delegated_credentials = credentials.with_subject(google_auth_with)

    service_name = 'cloudidentity'
    api_version = 'v1'
    service = googleapiclient.discovery.build(
        service_name,
        api_version,
        credentials=delegated_credentials)
    
    return service

def create_google_group(service, group_id, group_display_name, group_description):
    group_key = {"id": group_id}
    group = {
        "parent": "customers/" + google_customer_key,
        "description": group_description,
        "displayName": group_display_name,
        "groupKey": group_key,
        # Set the label to specify creation of a Google Group.
        "labels": {
            "cloudidentity.googleapis.com/groups.discussion_forum": ""
        }
    }

    try:
        request = service.groups().create(body=group)
        request.uri += "&initialGroupConfig=WITH_INITIAL_OWNER"
        response = request.execute()
        print(response)
    except Exception as e:
        print(e)

def search_google_groups(service):
    search_query = urlencode({
        "query": "parent=='customerId/{}' && 'cloudidentity.googleapis.com/groups.discussion_forum' in labels".format(google_customer_key)
    })
    search_group_request = service.groups().search()
    param = "&" + search_query
    search_group_request.uri += param
    response = search_group_request.execute()

    return response

def create_google_group_membership(service, customer_id, group_id, member_key):
    param = "&groupKey.id=" + group_id + "&groupKey.namespace=customer/" + customer_id
    try:
        lookupGroupNameRequest = service.groups().lookup()
        lookupGroupNameRequest.uri += param
        # Given a group ID and namespace, retrieve the ID for parent group
        lookupGroupNameResponse = lookupGroupNameRequest.execute()
        groupName = lookupGroupNameResponse.get("name")
        # Create a membership object with a memberKey and a single role of type MEMBER
        membership = {
            "preferredMemberKey": {"id": member_key},
            "roles" : {
                "name" : "MEMBER",
                "expiryDetail": {
                    "expireTime": "2021-10-02T15:01:23Z"
                }
            }
        }
        # Create a membership using the ID for the parent group and a membership object
        response = service.groups().memberships().create(parent=groupName, body=membership).execute()
        print(response)
    except Exception as e:
        print(e)

def create_burner(burner_email, burner_description, purchaser_email, travel_email):

    service_context = create_service

    create_google_group(service_context, burner_email, burner_email, burner_description)
    create_google_group_membership(service_context, CUSTOMER_ID, burner_email, purchaser_email)
    create_google_group_membership(service_context, CUSTOMER_ID, burner_email, travel_email)
