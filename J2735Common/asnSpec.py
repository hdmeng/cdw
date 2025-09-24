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
with open('j2735_spec_2.pkl', 'wb') as f:
    pickle.dump(j2735_spec, f)