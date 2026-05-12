CREATE TABLE SolveTimes(
    TimeID INTEGER IDENTITY(1,1) PRIMARY KEY,
    UserID INTEGER FOREIGN KEY REFERENCES Users(UserID),
    SolveTime DECIMAL(10, 2) NOT NULL,
    PuzzleType NVARCHAR(20) NOT NULL,
    SolveAt DATETIME NOT NULL DEFAULT GETDATE(),
    SolveStatus NVARCHAR(20) NULL
);

CREATE NONCLUSTERED INDEX IX_SolveTimes_UserID_PuzzleType_SolveAt
    ON SolveTimes (UserID, PuzzleType, SolveAt DESC)
    INCLUDE (SolveTime, SolveStatus, TimeID);