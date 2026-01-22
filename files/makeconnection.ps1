Clear-Host
# makeconnection.ps1 - Connect a windows PC to the quEDU.
# Author: Sven Hagedoorn (23066776)
# Date:   Thu Nov 13 15:31:46 2025

# Helper function, to slow down the pace of the script and make the user verify that everything is in check
function Wait-ForUser {
    param(
        [string]$Message = "Type 'c' to continue..."
    )

    while ($true) {
        [string]$input_t = $(Write-Host "[x] $Message" -ForegroundColor Yellow -NoNewline; Read-Host)
        if ($input_t -eq "c" -or $input_t -eq "-c") { break }
        Format-Write -Message "Unrecognised input. Please type 'c' or '-c' to continue."
    }
    Start-Sleep -Seconds 1
}

function Format-Write {
    param(
        [string]$Message
    )
    Write-Host "[x] $Message" -ForegroundColor Yellow
}

Format-Write -Message "Start with the Ethernet cable unplugged"
# Step 1.A: List Net Adapters
Format-Write -Message "Step 1.A: Listing network adapters..."
Get-NetAdapter
Wait-ForUser -Message "Study this list, note the 'Name' and 'Status' column. Type 'c' to continue..."

# Step 1.B: List Net Adapters 
Wait-ForUser -Message "Now, plug the ethernet cable into the quEDU and PC. Type 'c' to continue..."
Format-Write -Message "Step 1.B: Listing network adapters..."
Get-NetAdapter
Wait-ForUser -Message "The list entries are the same as before, except that one status changed to 'up', this is your ethernet connection. Type 'c' to continue..."

Format-Write -Message "Step 1C. Enter your ethernet connection"
Format-Write -Message "From the above list, enter the exact name (first column) of the adapter whose status turned to 'up'"

while ($true) {
    $Ethername = Read-Host "Enter connection name"

    $adapter = Get-NetAdapter | Where-Object { $_.Name -eq $Ethername }

    if ($adapter) {
        if ($adapter.Status -eq "Up") {
            Format-Write -Message "Connection '$Ethername' found"
            break
        } else {
            Write-Warning "Connection '$Ethername' exists but is not Up. Is the cable connected?"
            Format-Write -Message "Try again."
        }
    } else {
        Write-Warning "Connection '$Ethername' not found."
        Format-Write -Message "Please enter the Name exactly as shown in the table."
    }
}
Start-Sleep -seconds 1

# Step 2: Remove conflicting IPs
Format-Write -Message "Step 2: Removing any conflicting quEDU IP (192.168.0.1) from $Ethername..."
$existing = Get-NetIPAddress -InterfaceAlias $Ethername -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq "192.168.0.1" }
foreach ($a in $existing) { Remove-NetIPAddress -InterfaceAlias $Ethername -IPAddress $a.IPAddress -Confirm:$false }
Wait-ForUser -Message "Conflicting IPs removed. Type 'c' to assign new IP $Ethername..."

# Step 3: Assign IP to Ethernet connection
Format-Write -Message "Step 3: Assigning 192.168.0.2/24 to $Ethername..."
# Check if it's already assigned
$existingIP = Get-NetIPAddress -InterfaceAlias $Ethername -AddressFamily IPv4 | Where-Object { $_.IPAddress -eq "192.168.0.2" }
if ($null -ne $existingIP) {
    Format-Write -Message "IP is already assigned, skipping"
} else {
    Format-Write -Message "Assigning 192.168.0.2/24 to $Ethername... "
    New-NetIPAddress -InterfaceAlias $Ethername -IPAddress 192.168.0.2 -PrefixLength 24
}
Wait-ForUser -Message "IP assigned. Type 'c' to display current IPs..."

# Step 4: Display IPs
Format-Write -Message "Step 4: Current IP address on $Ethername :"
    Get-NetIPAddress -InterfaceAlias $Ethername
Format-Write -Message "Check the list, make sure that 'PrefixLength' is 24, 'IPAddress' is 192.168.0.2 and 'AddressFamily' is IPv4"
Wait-ForUser -Message "Type 'c' set up the quEDUs IP adress..."
Start-Sleep -seconds 1

# Step 5: Set quEDU IP adress
Wait-ForUser -Message "Go to the quEDU and press 'ctrl+alt+T' to open the Debian terminal, type 'c' to continue..."
Wait-ForUser -Message "Type 'sudo ip addr add 192.168.0.1/24 dev eth0' and press enter, type 'c' to continue..."
Wait-ForUser -Message "Type 'sudo ip link set eth0 up' and press enter, type 'c' to continue..."
Wait-ForUser -Message "Optionally, type 'ip addr show eth0' to confirm, look for the IP adress in the output, type 'c' to continue..."
Wait-ForUser -Message "quEDU IP is set up, type 'c' to test connection..."

# Step 6: Ping quEDU
Format-Write -Message "Step 6: Pinging quEDU at 192.168.0.1..."
ping 192.168.0.1

Wait-ForUser -Message "Ping complete. Type 'c' to finish the script."
Format-Write -Message "All steps complete!"
Start-Sleep -seconds 1

daisy.exe