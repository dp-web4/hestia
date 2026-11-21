param(
    [Parameter(Mandatory = $true)][string]$Path,
    [string]$OtherSid = "S-1-5-20"
)

$source = @'
using System;
using System.ComponentModel;
using System.Runtime.InteropServices;

public static class AuthzEffectiveProbe
{
    [StructLayout(LayoutKind.Sequential)]
    private struct AUTHZ_ACCESS_REQUEST
    {
        public uint DesiredAccess;
        public IntPtr PrincipalSelfSid;
        public IntPtr ObjectTypeList;
        public uint ObjectTypeListLength;
        public IntPtr OptionalArguments;
    }

    [StructLayout(LayoutKind.Sequential)]
    private struct AUTHZ_ACCESS_REPLY
    {
        public uint ResultListLength;
        public IntPtr GrantedAccessMask;
        public IntPtr SaclEvaluationResults;
        public IntPtr Error;
    }

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern uint GetNamedSecurityInfo(
        string objectName,
        uint objectType,
        uint securityInformation,
        out IntPtr owner,
        out IntPtr group,
        out IntPtr dacl,
        out IntPtr sacl,
        out IntPtr securityDescriptor);

    [DllImport("advapi32.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool ConvertStringSidToSidW(string stringSid, out IntPtr sid);

    [DllImport("authz.dll", SetLastError = true)]
    private static extern bool AuthzInitializeContextFromSid(
        uint flags,
        IntPtr userSid,
        IntPtr resourceManager,
        IntPtr expirationTime,
        long identifier,
        IntPtr dynamicGroupArgs,
        out IntPtr clientContext);

    [DllImport("authz.dll", SetLastError = true)]
    private static extern bool AuthzAccessCheck(
        uint flags,
        IntPtr clientContext,
        ref AUTHZ_ACCESS_REQUEST request,
        IntPtr auditEvent,
        IntPtr securityDescriptor,
        IntPtr optionalSecurityDescriptorArray,
        uint optionalSecurityDescriptorCount,
        ref AUTHZ_ACCESS_REPLY reply,
        out IntPtr accessCheckResults);

    [DllImport("authz.dll", CharSet = CharSet.Unicode, SetLastError = true)]
    private static extern bool AuthzInitializeResourceManager(
        uint flags,
        IntPtr dynamicAccessCheck,
        IntPtr computeDynamicGroups,
        IntPtr freeDynamicGroups,
        string resourceManagerName,
        out IntPtr resourceManager);

    [DllImport("authz.dll")]
    private static extern bool AuthzFreeResourceManager(IntPtr resourceManager);

    [DllImport("authz.dll")]
    private static extern bool AuthzFreeContext(IntPtr clientContext);

    [DllImport("kernel32.dll")]
    private static extern IntPtr LocalFree(IntPtr memory);

    public static uint[] Check(string path, string stringSid, uint desiredAccess)
    {
        IntPtr owner = IntPtr.Zero, group = IntPtr.Zero, dacl = IntPtr.Zero, sacl = IntPtr.Zero;
        IntPtr securityDescriptor = IntPtr.Zero, sid = IntPtr.Zero, context = IntPtr.Zero;
        IntPtr resourceManager = IntPtr.Zero;
        IntPtr granted = IntPtr.Zero, saclResults = IntPtr.Zero, error = IntPtr.Zero;
        try
        {
            uint result = GetNamedSecurityInfo(path, 1, 5, out owner, out group, out dacl, out sacl,
                                               out securityDescriptor);
            if (result != 0) throw new Win32Exception((int)result);
            if (!ConvertStringSidToSidW(stringSid, out sid)) throw new Win32Exception();
            if (!AuthzInitializeResourceManager(1, IntPtr.Zero, IntPtr.Zero, IntPtr.Zero,
                                                "HestiaACLProbe", out resourceManager)) throw new Win32Exception();
            if (!AuthzInitializeContextFromSid(2, sid, resourceManager, IntPtr.Zero, 0, IntPtr.Zero,
                                               out context)) throw new Win32Exception();

            var request = new AUTHZ_ACCESS_REQUEST
            {
                DesiredAccess = desiredAccess,
                PrincipalSelfSid = sid,
                ObjectTypeList = IntPtr.Zero,
                ObjectTypeListLength = 0,
                OptionalArguments = IntPtr.Zero,
            };
            granted = Marshal.AllocHGlobal(sizeof(uint));
            saclResults = Marshal.AllocHGlobal(sizeof(uint));
            error = Marshal.AllocHGlobal(sizeof(uint));
            Marshal.WriteInt32(granted, 0);
            Marshal.WriteInt32(saclResults, 0);
            Marshal.WriteInt32(error, 0);
            var reply = new AUTHZ_ACCESS_REPLY
            {
                ResultListLength = 1,
                GrantedAccessMask = granted,
                SaclEvaluationResults = saclResults,
                Error = error,
            };
            IntPtr accessCheckResults;
            if (!AuthzAccessCheck(0, context, ref request, IntPtr.Zero, securityDescriptor,
                                  IntPtr.Zero, 0, ref reply, out accessCheckResults)) throw new Win32Exception();
            return new[] { (uint)Marshal.ReadInt32(granted), (uint)Marshal.ReadInt32(error) };
        }
        finally
        {
            if (granted != IntPtr.Zero) Marshal.FreeHGlobal(granted);
            if (saclResults != IntPtr.Zero) Marshal.FreeHGlobal(saclResults);
            if (error != IntPtr.Zero) Marshal.FreeHGlobal(error);
            if (context != IntPtr.Zero) AuthzFreeContext(context);
            if (resourceManager != IntPtr.Zero) AuthzFreeResourceManager(resourceManager);
            if (sid != IntPtr.Zero) LocalFree(sid);
            if (securityDescriptor != IntPtr.Zero) LocalFree(securityDescriptor);
        }
    }
}
'@

Add-Type -TypeDefinition $source
$currentSid = [System.Security.Principal.WindowsIdentity]::GetCurrent().User.Value
$read = [uint32]1
$write = [uint32]2
$currentRead = [AuthzEffectiveProbe]::Check($Path, $currentSid, $read)
$currentWrite = [AuthzEffectiveProbe]::Check($Path, $currentSid, $write)
$otherRead = [AuthzEffectiveProbe]::Check($Path, $OtherSid, $read)
$otherWrite = [AuthzEffectiveProbe]::Check($Path, $OtherSid, $write)
$result = [ordered]@{
    current = [ordered]@{
        read_mask = $currentRead[0]
        write_mask = $currentWrite[0]
        read_error = $currentRead[1]
        write_error = $currentWrite[1]
    }
    other = [ordered]@{
        sid = $OtherSid
        read_mask = $otherRead[0]
        write_mask = $otherWrite[0]
        read_error = $otherRead[1]
        write_error = $otherWrite[1]
    }
}
$result | ConvertTo-Json -Depth 3
if ($currentRead[0] -ne $read -or $currentWrite[0] -ne $write -or
    $currentRead[1] -ne 0 -or $currentWrite[1] -ne 0 -or
    $otherRead[0] -ne 0 -or $otherWrite[0] -ne 0 -or
    $otherRead[1] -ne 5 -or $otherWrite[1] -ne 5) {
    throw "effective access did not match current-user allow / other-SID deny"
}
