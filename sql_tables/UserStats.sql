CREATE TABLE UserStats (
    StatID INT PRIMARY KEY IDENTITY(1,1),
    UserID INT NOT NULL,
    PuzzleType VARCHAR(20) NOT NULL,
    BestSingle DECIMAL(10, 2) NULL,
    BestAo5 DECIMAL(10, 2) NULL,
    BestAo12 DECIMAL(10, 2) NULL,
    CONSTRAINT FK_UserStats_Users FOREIGN KEY (UserID) REFERENCES Users(UserID)
);

CREATE UNIQUE NONCLUSTERED INDEX UX_UserStats_UserID_PuzzleType
    ON UserStats (UserID, PuzzleType)
    INCLUDE (BestSingle, BestAo5, BestAo12);