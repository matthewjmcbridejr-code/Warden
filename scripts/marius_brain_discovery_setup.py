import argparse
import sys
import time
from google.cloud import discoveryengine_v1 as discoveryengine
from google.api_core import exceptions

def setup_discovery_engine(args):
    project_id = args.project
    location = args.location
    data_store_id = args.data_store_id
    engine_id = args.engine_id
    bucket_uri = args.bucket_uri
    
    parent = f"projects/{project_id}/locations/{location}/collections/default_collection"
    
    print(f"== Marius Brain Discovery Engine Setup ==")
    print(f"Project:  {project_id}")
    print(f"Location: {location}")
    print(f"Plan:")
    
    # Check if Data Store exists
    ds_client = discoveryengine.DataStoreServiceClient()
    ds_name = f"{parent}/dataStores/{data_store_id}"
    
    ds_exists = False
    try:
        ds_client.get_data_store(name=ds_name)
        print(f"  - Data Store '{data_store_id}' already exists.")
        ds_exists = True
    except exceptions.NotFound:
        print(f"  - WILL CREATE Data Store: {data_store_id}")
    except Exception as e:
        print(f"  - Error checking Data Store: {e}")
        return

    # Check if Engine exists
    eng_client = discoveryengine.EngineServiceClient()
    eng_name = f"{parent}/engines/{engine_id}"
    
    eng_exists = False
    try:
        eng_client.get_engine(name=eng_name)
        print(f"  - Engine '{engine_id}' already exists.")
        eng_exists = True
    except exceptions.NotFound:
        print(f"  - WILL CREATE Engine: {engine_id}")
    except Exception as e:
        print(f"  - Error checking Engine: {e}")
        return

    if not args.create and not args.import_docs:
        print("\nDry run by default. Use --create to apply infrastructure or --import to load docs.")
        return

    if args.create:
        if not ds_exists:
            print(f"\nCreating Data Store '{data_store_id}'...")
            try:
                data_store = discoveryengine.DataStore(
                    display_name="Marius Brain Warden",
                    industry_vertical=discoveryengine.IndustryVertical.GENERIC,
                    content_config=discoveryengine.DataStore.ContentConfig.CONTENT_REQUIRED,
                    solution_types=[discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH]
                )
                operation = ds_client.create_data_store(
                    parent=parent,
                    data_store=data_store,
                    data_store_id=data_store_id
                )
                print(f"Waiting for operation: {operation.operation.name}")
                operation.result()
                print("Data Store created.")
            except Exception as e:
                print(f"Failed to create Data Store: {e}")
                return

        if not eng_exists:
            print(f"\nCreating Engine '{engine_id}'...")
            try:
                engine = discoveryengine.Engine(
                    display_name="Marius Brain",
                    solution_type=discoveryengine.SolutionType.SOLUTION_TYPE_SEARCH,
                    data_store_ids=[data_store_id],
                    search_engine_config=discoveryengine.Engine.SearchEngineConfig(
                        search_tier=discoveryengine.Engine.SearchTier.SEARCH_TIER_ENTERPRISE,
                        search_add_ons=[discoveryengine.Engine.SearchTier.SEARCH_TIER_ENTERPRISE]
                    )
                )
                operation = eng_client.create_engine(
                    parent=parent,
                    engine=engine,
                    engine_id=engine_id
                )
                print(f"Waiting for operation: {operation.operation.name}")
                operation.result()
                print("Engine created.")
            except Exception as e:
                print(f"Failed to create Engine: {e}")
                return

    if args.import_docs and bucket_uri:
        print(f"\nImporting documents from {bucket_uri}...")
        try:
            doc_client = discoveryengine.DocumentServiceClient()
            request = discoveryengine.ImportDocumentsRequest(
                parent=f"{ds_name}/branches/0", # default branch
                gcs_source=discoveryengine.GcsSource(
                    input_uris=[bucket_uri],
                    data_schema="content" # JSONL one record per line
                ),
                reconciliation_mode=discoveryengine.ImportDocumentsRequest.ReconciliationMode.INCREMENTAL
            )
            operation = doc_client.import_documents(request=request)
            print(f"Waiting for import: {operation.operation.name}")
            # Do not wait for potentially long import, just return
            print("Import started. Check progress in Google Cloud Console.")
        except Exception as e:
            print(f"Failed to import documents: {e}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Marius Brain Discovery Engine Setup")
    parser.add_argument("--project", default="project-b11857c2-0ddb-4154-802")
    parser.add_argument("--location", default="global")
    parser.add_argument("--data-store-id", default="marius-brain-warden")
    parser.add_argument("--engine-id", default="marius-brain")
    parser.add_argument("--bucket-uri", help="gs://bucket/path/to/warden.jsonl")
    parser.add_argument("--create", action="store_true", help="Create DS and Engine")
    parser.add_argument("--import", dest="import_docs", action="store_true", help="Import docs from GCS")
    
    args = parser.parse_args()
    
    try:
        setup_discovery_engine(args)
    except Exception as e:
        print(f"FATAL: {e}")
