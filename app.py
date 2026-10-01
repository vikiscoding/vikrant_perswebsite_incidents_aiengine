from cmdb import Cmdb
from company import get_company

def test_setup():
    print("\n--- Phase 1: Environment Verification ---")
    try:
        cmdb = Cmdb.load()
        print(f"✅ Success: Loaded and validated {len(cmdb.items)} CMDB records for {get_company().name}.")
        print(f"Sample Item: {cmdb.items[0].name} ({cmdb.items[0].ci_id}) -> Owned by {cmdb.items[0].owner_team}")
    except Exception as e:
        print(f"❌ Error during file validation: {e}")

if __name__ == "__main__":
    test_setup()
