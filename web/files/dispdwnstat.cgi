<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="default.css" rel="stylesheet">
<script src="rollover.js"></script>
<title>Upload Complete</title>
</head>
<body class="ui">
<h1>Upload Complete</h1>
<section>
  <p class="check-result good">The file has been sent to the TFTP server.</p>
  <button type="button" class="btn primary" onclick="redirect()">Continue</button>
</section>

<script>
PaintButtons("");   // no shell buttons on this page
function redirect() { document.location.href = "fileUpload.html"; }
</script>
</body>
</html>
