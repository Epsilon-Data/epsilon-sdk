from archetypes.healthcare_db.healthcare_db import create_dataset


def main():
    dataset = create_dataset()
    print(f"Loaded dataset with {len(dataset)} records")
    print("Analysis Results:", dataset)
    for record in dataset:
        print(record.patient.patient_id)


if __name__ == "__main__":
    main()