import os
import sys
from google.cloud import discoveryengine_v1 as discoveryengine

def probe_discovery_engine():
    project_id = "project-b11857c2-0ddb-4154-802"
    locations = ["global", "us", "eu"]
    
    print(f"== Probing Discovery Engine for project: {project_id} ==")
    
    try:
        client = discoveryengine.DataStoreServiceClient()
        engine_client = discoveryengine.EngineServiceClient()
        
        for location in locations:
            print(f"\nLocation: {location}")
            parent = f"projects/{project_id}/locations/{location}/collections/default_collection"
            
            # List Data Stores
            print("  Data Stores:")
            try:
                data_stores = client.list_data_stores(parent=parent)
                count = 0
                for ds in data_stores:
                    print(f"    - {ds.name} (Display: {ds.display_name})")
                    count += 1
                if count == 0:
                    print("    (None found)")
            except Exception as e:
                print(f"    Error listing data stores: {e}")
                
            # List Engines
            print("  Engines/Apps:")
            try:
                engines = engine_client.list_engines(parent=parent)
                count = 0
                for eng in engines:
                    print(f"    - {eng.name} (Display: {eng.display_name})")
                    count += 1
                if count == 0:
                    print("    (None found)")
            except Exception as e:
                print(f"    Error listing engines: {e}")
                
    except Exception as e:
        print(f"FATAL: {e}")

if __name__ == "__main__":
    probe_discovery_engine()
