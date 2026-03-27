// Code.gs
// Deploy as Web App: Execute as "Me", Access "Anyone"

const SPREADSHEET_ID = "";  // from your existing Sheet URL
const SHEET_NAME = "Sheet1";
const SECRET_KEY = "";    // make up any string, e.g. "funhouse-abc123"
                                                 // store this same value in settings.toml

function doPost(e) {
  try {
    // --- Parse incoming JSON ---
    var raw = e.postData.contents;
    var data = JSON.parse(raw);

    // --- Validate secret key ---
    if (data.key !== SECRET_KEY) {
      return respond(403, "Unauthorized");
    }

    // --- Validate required fields ---
    var required = ["timestamp", "energy", "temperature", "humidity", "motion"];
    for (var i = 0; i < required.length; i++) {
      if (data[required[i]] === undefined || data[required[i]] === null) {
        return respond(400, "Missing field: " + required[i]);
      }
    }

    // --- Validate value ranges ---
    if (data.energy < 0 || data.energy > 100) {
      return respond(400, "energy out of range (0-100)");
    }
    if (data.temperature < -40 || data.temperature > 85) {
      return respond(400, "temperature out of range");
    }
    if (data.humidity < 0 || data.humidity > 100) {
      return respond(400, "humidity out of range");
    }

    // --- Write to sheet ---
    var sheet = SpreadsheetApp
      .openById(SPREADSHEET_ID)
      .getSheetByName(SHEET_NAME);

    // Add header row if sheet is empty
    if (sheet.getLastRow() === 0) {
      sheet.appendRow(["Timestamp", "Energy", "Temperature (C)", "Humidity (%)", "Motion", "Received At"]);
    }

    var receivedAt = new Date().toISOString();
    sheet.appendRow([
      data.timestamp,
      data.energy,
      data.temperature,
      data.humidity,
      data.motion,
      receivedAt
    ]);

    return respond(200, "OK");

  } catch (err) {
    return respond(500, "Server error: " + err.message);
  }
}

// --- Helper: doGet lets you test the endpoint is live in a browser ---
function doGet(e) {
  return respond(200, "Funhouse logger is alive.");
}

function respond(code, message) {
  var payload = JSON.stringify({ status: code, message: message });
  return ContentService
    .createTextOutput(payload)
    .setMimeType(ContentService.MimeType.JSON);
}
