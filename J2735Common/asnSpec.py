import asn1tools
import pickle
import os

# Provide the correct path to the ASN.1 specification file
asn_path = './V2X_ASN1_Module_2020-07-01'
asn1_files = [
    os.path.join(asn_path, 'J2735-Common.asn'),
    os.path.join(asn_path, 'J2735-MapData.asn'),
    os.path.join(asn_path, 'J2735-ITIS.asn'),
    os.path.join(asn_path, 'J2735-BasicSafetyMessage.asn'),
    os.path.join(asn_path, 'J2735-NTCIP.asn'),
    os.path.join(asn_path, 'J2735-MessageFrame.asn'),
    os.path.join(asn_path, 'J2735-SPAT.asn'),
    os.path.join(asn_path, 'J2735-TravelerInformation.asn'),
]

# Load the ASN.1 specification for J2735
j2735_spec = asn1tools.compile_files(asn1_files, 'uper')

    # Save the compiled ASN.1 specification to a file
if not os.path.exists('./pkl/pklj2735_spec_2.pkl'):
    with open('./pkl/j2735_spec_2.pkl', 'wb') as f:
        pickle.dump(j2735_spec, f)

# updae for 2024 version
asn_path = './V2X_ASN1_Module_Collection_2024'
asn1_files = [
    os.path.join(asn_path, 'J2735-ITIS-2024-rel-v1.1.asn'),
    os.path.join(asn_path, 'J2735-Common-2024-rel-v1.1.2.asn'),
    os.path.join(asn_path, 'J2735-MapData-2024-rel-v1.1.asn'),
    os.path.join(asn_path, 'J2735-ProbeVehicleData-2024-rel-v1.1.asn'),
    os.path.join(asn_path, 'J2945-3-RoadWeatherMessage-2024-rel-v2.1.asn'),
    os.path.join(asn_path, 'J2945-C-ProbeDataConfig-2024-rel-v1.1.asn'),
    os.path.join(asn_path, 'J2945-C-ProbeDataReport-2024-rel-v1.1.asn'),
    os.path.join(asn_path, 'J2735-BasicSafetyMessage-2024-rel-v1.1.2.asn'),
    os.path.join(asn_path, 'J2735-NTCIP-2024-rel-v1.1.asn'),
    os.path.join(asn_path, 'J2735-MessageFrame-2024-rel-v1.1.1.asn'),
    os.path.join(asn_path, 'J2735-SPAT-2024-rel-v1.1.1.asn'),
    os.path.join(asn_path, 'J2735-TravelerInformation-2024-rel-v1.1.2.asn'),
]

# Load the ASN.1 specification for J2735
j2735_spec = asn1tools.compile_files(asn1_files, 'uper')

if not os.path.exists('./pkl/j2735_spec_2024.pkl'):
    # Save the compiled ASN.1 specification to a file
    with open('./pkl/j2735_spec_2024.pkl', 'wb') as f:
        pickle.dump(j2735_spec, f)