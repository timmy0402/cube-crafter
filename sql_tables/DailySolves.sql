CREATE TABLE DailySolves(
    SolveID INTEGER IDENTITY(1,1) PRIMARY KEY,
    UserID INTEGER FOREIGN KEY REFERENCES Users(UserID),
    SolveTime FLOAT NOT NULL,
    SolveDate DATE NOT NULL DEFAULT GETDATE(),
    SolveStatus NVARCHAR(20) NOT NULL,
);

CREATE NONCLUSTERED INDEX IX_DailySolves_UserID_SolveDate
    ON DailySolves (UserID, SolveDate)
    INCLUDE (SolveTime, SolveStatus);