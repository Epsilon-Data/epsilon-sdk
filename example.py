# from archetypes.4f7a5238_a3b7_46d1_93bc_c2323fb7e559 import create_dataset

def main():
    dataset = create_dataset()
    print(f"Loaded dataset with {len(dataset)} records")
    print("Analysis Results:", dataset)
    for record in dataset:
        print(record.patient.patient_id)


if __name__ == "__main__":
    main()