<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link href="default.css" rel="stylesheet">
<script src="rollover.js"></script>
<title>Firmware Upgrade</title>
</head>
<body class="ui">
<h1 id="title">Firmware Upgrade</h1>
<p class="lead">The switch is downloading the image from the TFTP server and writing it to flash. Do not power off the switch.</p>
<section>
<div class="progress" id="progress">
  <div class="bar"><div id="bar"></div></div>
  <p id="progressText">Starting transfer&hellip;</p>
</div>
</section>
<form name="upg" method="post" action="dispstat.cgi" enctype="multipart/form-data"></form>

<script>
PaintButtons("");   // no shell buttons on this page
var itype = "{{var fn=0x8006f0ec id=3}}";
if (parseInt(itype) != 0) { document.getElementById("title").textContent = "Boot Code Upgrade"; document.title = "Boot Code Upgrade"; }

// Progress: the hidden frame iw1 loads getdwnstatus.html, which calls parent.window.update(current, total, tftp_status).
var t_interval = 1000, phase = 0;
function setBar(pt, text) {
  document.getElementById("bar").style.width = pt + "%";
  document.getElementById("progressText").textContent = text;
}
function start_upgrade() {
  phase = 1;
  setTimeout(check, 250);
}
function update(current, total, tftp_status) {
  if (tftp_status == 1) document.upg.submit();          // transfer finished: continue to dispstat.cgi
  if (current < 0 || phase == 3) {
    phase = 3;
    document.getElementById("progress").className = "progress failed";
    alert("Error in downloading firmware!");
    document.location.href = "fileDownload.html";
    return;
  }
  setTimeout(check, t_interval);
  if (total == 0) return;
  var pt = Math.floor(current * 100 / total);
  if (pt <= 0) return;
  if (pt >= 100) pt = 99;
  phase = 2;
  setBar(pt, current + " bytes written (" + pt + "%)");
}
function check() { iw1.location = "getdwnstatus.html"; }

window.addEventListener("load", start_upgrade);
</script>
<iframe src="getdwnstatus.html" name="iw1" width="0" height="0" hidden></iframe>
</body>
</html>
