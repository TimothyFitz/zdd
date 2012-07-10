var http = require('http');
var fs = require('fs');

var server = http.createServer(function (req, res) { 
    res.writeHead(200, {'Content-Type': 'text/plain'});
    res.end("Hello World (node.js)\n");
}); 


var unlinkSync = function (filename) {
    try {
        fs.unlinkSync(filename);
    } catch (error) {
        if (error.code != "ENOENT") {
            throw error;
        }
    }
};

// Write the pid and port file, and listen to process exit to remove the files later
server.addListener("listening", function () { 
    var pid = process.pid;
    var port = server.address().port;

    var pid_filename = "node.pid";
    var port_filename = pid.toString() + ".port";

    console.log("port", server.address().port, "pid", process.pid);

    fs.writeFile(pid_filename, pid.toString() + "\n");
    fs.writeFile(port_filename, port.toString() + "\n");

    var cleanupSync = function () {
        unlinkSync(pid_filename);
        unlinkSync(port_filename);
    };

    // I would love a better way of doing this, but there's no straightforward atexit
    process.on('exit', cleanupSync);
    process.on('SIGTERM', cleanupSync);
    process.on('SIGINT', function () {
        // By default SIGINT won't generate an 'exit' signal, but this will.
        process.exit();
    });
});

server.listen(0);