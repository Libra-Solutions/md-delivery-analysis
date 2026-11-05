CREATE TABLE cohort_member (
    person_id TEXT PRIMARY KEY REFERENCES person(person_id),
    level TEXT NOT NULL CHECK (level IN ('Mid', 'Senior')),
    day0 TEXT NOT NULL
);
